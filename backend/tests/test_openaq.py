import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest

from app.models.contracts import DataType, ReportStatus, RoutineRequest
from app.services.exposure import OpenMeteoAirQualityAdapter, create_provider_report
from app.services.openaq import (
    OpenAQAirQualityAdapter,
    OpenAQProviderError,
)


START = datetime(2026, 10, 10, 8, tzinfo=UTC)
NOW = datetime(2026, 10, 10, 9, 30, tzinfo=UTC)


def response(payload: object, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("GET", "https://api.openaq.org/v3"),
    )


def test_openaq_adapter_discovers_sensor_and_parses_fresh_measurement() -> None:
    client = AsyncMock()
    client.get.side_effect = [
        response(
            {
                "results": [
                    {
                        "id": 10,
                        "coordinates": {"latitude": 28.601, "longitude": 77.201},
                    }
                ]
            }
        ),
        response(
            {
                "results": [
                    {
                        "id": 20,
                        "parameter": {"name": "pm25", "units": "µg/m³"},
                    },
                    {
                        "id": 21,
                        "parameter": {"name": "pm10", "units": "µg/m³"},
                    },
                ]
            }
        ),
        response(
            {
                "results": [
                    {
                        "value": 42.5,
                        "parameter": {"name": "pm25", "units": "µg/m³"},
                        "period": {
                            "datetimeFrom": {"utc": "2026-10-10T08:00:00Z"}
                        },
                    }
                ]
            }
        ),
    ]

    readings = asyncio.run(
        OpenAQAirQualityAdapter(api_key="test-key", client=client).fetch_pm25(
            28.6, 77.2, START, START + timedelta(hours=1), now=NOW
        )
    )

    assert len(readings) == 1
    assert readings[0].concentration == pytest.approx(42.5)
    assert client.get.call_args_list[0].kwargs["headers"]["x-api-key"] == "test-key"
    assert client.get.call_args_list[2].kwargs["params"]["datetime_from"] == (
        "2026-10-10T08:00:00Z"
    )


def test_openaq_rejects_missing_or_unsuitable_measurements() -> None:
    client = AsyncMock()
    client.get.side_effect = [
        response(
            {
                "results": [
                    {
                        "id": 10,
                        "coordinates": {"latitude": 28.601, "longitude": 77.201},
                    }
                ]
            }
        ),
        response(
            {
                "results": [
                    {
                        "id": 20,
                        "parameter": {"name": "pm25", "units": "ppm"},
                    }
                ]
            }
        ),
    ]

    with pytest.raises(OpenAQProviderError, match="no PM2.5 sensor"):
        asyncio.run(
            OpenAQAirQualityAdapter(api_key="test-key", client=client).fetch_pm25(
                28.6, 77.2, START, START + timedelta(hours=1), now=NOW
            )
        )


def test_openaq_http_errors_are_explicit() -> None:
    client = AsyncMock()
    client.get.side_effect = httpx.ReadTimeout("timed out")

    with pytest.raises(OpenAQProviderError):
        asyncio.run(
            OpenAQAirQualityAdapter(api_key="test-key", client=client).fetch_pm25(
                28.6, 77.2, START, START + timedelta(hours=1), now=NOW
            )
        )


@pytest.mark.parametrize(
    "failure",
    [
        ValueError("malformed JSON"),
        httpx.HTTPStatusError(
            "unauthorized",
            request=httpx.Request("GET", "https://api.openaq.org/v3"),
            response=response({}, 401),
        ),
        httpx.ReadTimeout("timed out"),
    ],
)
def test_openaq_normalizes_response_failures(failure: Exception) -> None:
    client = AsyncMock()
    client.get.side_effect = failure

    with pytest.raises(OpenAQProviderError, match="request or response failed"):
        asyncio.run(
            OpenAQAirQualityAdapter(api_key="test-key", client=client).fetch_pm25(
                28.6, 77.2, START, START + timedelta(hours=1), now=NOW
            )
        )


def test_openaq_rejects_non_finite_measurements() -> None:
    client = AsyncMock()
    client.get.side_effect = [
        response(
            {
                "results": [
                    {
                        "id": 10,
                        "coordinates": {"latitude": 28.601, "longitude": 77.201},
                    }
                ]
            }
        ),
        response(
            {
                "results": [
                    {
                        "id": 20,
                        "parameter": {"name": "pm25", "units": "µg/m³"},
                    }
                ]
            }
        ),
        httpx.Response(
            200,
            content=(
                b'{"results":[{"value":NaN,"parameter":{"name":"pm25",'
                b'"units":"ug/m3"},"period":{"datetimeFrom":'
                b'{"utc":"2026-10-10T08:00:00Z"}}}]}'
            ),
            request=httpx.Request("GET", "https://api.openaq.org/v3"),
        ),
    ]

    with pytest.raises(OpenAQProviderError, match="no fresh"):
        asyncio.run(
            OpenAQAirQualityAdapter(api_key="test-key", client=client).fetch_pm25(
                28.6, 77.2, START, START + timedelta(hours=1), now=NOW
            )
        )


def test_openaq_is_used_only_when_open_meteo_has_no_usable_value() -> None:
    routine = RoutineRequest(
        start_time=START,
        stops=[
            {
                "label": "Home",
                "duration_minutes": 60,
                "coordinates": {"latitude": 28.6, "longitude": 77.2},
            }
        ],
    )
    meteo = AsyncMock(spec=OpenMeteoAirQualityAdapter)
    meteo.fetch_hourly_pm25.return_value = ()
    openaq = AsyncMock()
    openaq.fetch_pm25.return_value = (
        type(
            "Reading",
            (),
            {"timestamp": START, "concentration": 42.5},
        )(),
    )

    report = asyncio.run(
        create_provider_report(
            routine,
            adapter=meteo,
            openaq_adapter=openaq,
            now=NOW,
        )
    )

    assert report.status is ReportStatus.AVAILABLE
    assert report.pm25_value == pytest.approx(42.5)
    assert report.provenance.data_type is DataType.OBSERVATION
    assert report.provenance.sources == ["OpenAQ ground-monitor measurement"]
    meteo.fetch_hourly_pm25.assert_awaited_once()
    openaq.fetch_pm25.assert_awaited_once()


def test_openaq_is_not_combined_with_usable_open_meteo_data() -> None:
    routine = RoutineRequest(
        start_time=START,
        stops=[
            {
                "label": "Home",
                "duration_minutes": 60,
                "coordinates": {"latitude": 28.6, "longitude": 77.2},
            }
        ],
    )
    meteo = AsyncMock(spec=OpenMeteoAirQualityAdapter)
    meteo.fetch_hourly_pm25.return_value = (
        type("Reading", (), {"timestamp": START, "concentration": 20})(),
    )
    openaq = AsyncMock()

    report = asyncio.run(
        create_provider_report(routine, adapter=meteo, openaq_adapter=openaq)
    )

    assert report.pm25_value == pytest.approx(20)
    openaq.fetch_pm25.assert_not_awaited()

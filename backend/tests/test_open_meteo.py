import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest

from app.models.contracts import ReportStatus, RoutineRequest
from app.services.exposure import (
    OpenMeteoAirQualityAdapter,
    OpenMeteoProviderError,
    create_provider_report,
)


START = datetime(2026, 10, 10, 8, tzinfo=UTC)


def routine() -> RoutineRequest:
    return RoutineRequest(
        start_time=START,
        stops=[
            {
                "label": "Home",
                "duration_minutes": 120,
                "coordinates": {"latitude": 28.6, "longitude": 77.2},
            },
            {
                "label": "Office",
                "duration_minutes": 480,
                "coordinates": {"latitude": 28.61, "longitude": 77.21},
            },
        ],
    )


def response(payload: object, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("GET", "https://example.test"),
    )


def test_adapter_parses_hourly_pm25_and_omits_missing_values() -> None:
    client = AsyncMock()
    client.get.return_value = response(
        {
            "hourly": {
                "time": ["2026-10-10T08:00", "2026-10-10T09:00"],
                "pm2_5": [100, None],
            }
        }
    )
    adapter = OpenMeteoAirQualityAdapter(client=client)

    readings = asyncio.run(
        adapter.fetch_hourly_pm25(28.6, 77.2, START, START + timedelta(hours=2))
    )

    assert len(readings) == 1
    assert readings[0].concentration == 100
    assert client.get.call_args.kwargs["params"] == {
        "latitude": 28.6,
        "longitude": 77.2,
        "hourly": "pm2_5",
        "timezone": "UTC",
        "start_date": "2026-10-10",
        "end_date": "2026-10-10",
    }


def test_provider_report_uses_matching_hourly_readings() -> None:
    adapter = AsyncMock(spec=OpenMeteoAirQualityAdapter)
    adapter.fetch_hourly_pm25.side_effect = [
        (
            type("Reading", (), {"timestamp": START, "concentration": 100})(),
            type(
                "Reading",
                (),
                {"timestamp": START.replace(hour=9), "concentration": 100},
            )(),
        ),
        (
            *[
                type(
                    "Reading",
                    (),
                    {"timestamp": START.replace(hour=hour), "concentration": 25},
                )()
                for hour in range(10, 18)
            ],
        ),
    ]

    report = asyncio.run(create_provider_report(routine(), adapter=adapter))

    assert report.status is ReportStatus.AVAILABLE
    assert report.pm25_value == pytest.approx(40)
    assert report.coverage.ratio == pytest.approx(1)
    assert report.provenance.source.startswith("Open-Meteo")


def test_missing_values_return_explicit_unavailable_report() -> None:
    adapter = AsyncMock(spec=OpenMeteoAirQualityAdapter)
    adapter.fetch_hourly_pm25.return_value = ()

    report = asyncio.run(create_provider_report(routine(), adapter=adapter))

    assert report.status is ReportStatus.UNAVAILABLE
    assert report.pm25_value is None
    assert report.error_code == "NO_USABLE_PM25_DATA"


def test_partial_hour_missing_data_reduces_usable_coverage() -> None:
    partial_routine = RoutineRequest(
        start_time=START.replace(minute=30),
        stops=[
            {
                "label": "Home",
                "duration_minutes": 60,
                "coordinates": {"latitude": 28.6, "longitude": 77.2},
            }
        ],
    )
    adapter = AsyncMock(spec=OpenMeteoAirQualityAdapter)
    adapter.fetch_hourly_pm25.return_value = (
        type("Reading", (), {"timestamp": START.replace(hour=9), "concentration": 25})(),
    )

    report = asyncio.run(create_provider_report(partial_routine, adapter=adapter))

    assert report.status is ReportStatus.AVAILABLE
    assert report.pm25_value == pytest.approx(25)
    assert report.coverage.usable_duration_minutes == pytest.approx(30)
    assert report.coverage.total_requested_duration_minutes == pytest.approx(60)
    assert report.coverage.ratio == pytest.approx(0.5)


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ReadTimeout("timed out"),
        httpx.HTTPStatusError(
            "bad response",
            request=httpx.Request("GET", "https://example.test"),
            response=response({}, 500),
        ),
        ValueError("malformed JSON"),
    ],
)
def test_adapter_normalizes_provider_failures(failure: Exception) -> None:
    client = AsyncMock()
    client.get.side_effect = failure
    adapter = OpenMeteoAirQualityAdapter(client=client)

    with pytest.raises(OpenMeteoProviderError):
        asyncio.run(
            adapter.fetch_hourly_pm25(28.6, 77.2, START, START + timedelta(hours=1))
        )


def test_invalid_provider_data_is_rejected() -> None:
    client = AsyncMock()
    client.get.return_value = response(
        {"hourly": {"time": ["2026-10-10T08:00"], "pm2_5": [-1]}}
    )

    with pytest.raises(OpenMeteoProviderError):
        asyncio.run(
            OpenMeteoAirQualityAdapter(client=client).fetch_hourly_pm25(
                28.6, 77.2, START, START + timedelta(hours=1)
            )
        )

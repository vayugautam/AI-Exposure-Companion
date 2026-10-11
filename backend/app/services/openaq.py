from datetime import UTC, datetime, timedelta
from math import asin, cos, isfinite, radians, sin, sqrt
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

from app.services.exposure import HourlyPM25Reading

load_dotenv(Path(__file__).resolve().parents[3] / ".env")


class OpenAQProviderError(Exception):
    """Raised when OpenAQ cannot provide a suitable PM2.5 reading."""


class OpenAQAirQualityAdapter:
    endpoint = "https://api.openaq.org/v3"
    source_name = "OpenAQ ground-monitor measurement"
    pm25_parameter_id = 2
    max_station_distance_meters = 25_000
    max_reading_age = timedelta(hours=3)

    def __init__(
        self,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout: httpx.Timeout | None = None,
    ) -> None:
        import os

        self._api_key = api_key or os.getenv("OPENAQ_API_KEY")
        self._client = client
        self._timeout = timeout or httpx.Timeout(10.0, connect=5.0)

    async def fetch_pm25(
        self,
        latitude: float,
        longitude: float,
        start: datetime,
        end: datetime,
        now: datetime | None = None,
    ) -> tuple[HourlyPM25Reading, ...]:
        if not self._api_key:
            raise OpenAQProviderError("OPENAQ_API_KEY is not configured")
        if start.tzinfo is None or end.tzinfo is None or end <= start:
            raise ValueError("start and end must be timezone-aware with end after start")

        own_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        headers = {"x-api-key": self._api_key, "accept": "application/json"}
        try:
            locations = await self._get_json(
                client,
                "/locations",
                headers,
                {
                    "coordinates": f"{latitude},{longitude}",
                    "radius": self.max_station_distance_meters,
                    "parameters_id": self.pm25_parameter_id,
                    "limit": 100,
                },
            )
            location = _nearest_location(
                locations.get("results"), latitude, longitude
            )
            if location is None:
                raise OpenAQProviderError("No nearby OpenAQ PM2.5 station found")

            sensors_payload = await self._get_json(
                client, f"/locations/{location['id']}/sensors", headers, {"limit": 100}
            )
            sensor = _select_pm25_sensor(sensors_payload.get("results"))
            if sensor is None:
                raise OpenAQProviderError("Nearby OpenAQ station has no PM2.5 sensor")

            measurements = await self._get_json(
                client,
                f"/sensors/{sensor['id']}/measurements",
                headers,
                {
                    "datetime_from": _format_openaq_time(start),
                    "datetime_to": _format_openaq_time(end),
                    "limit": 1000,
                },
            )
            readings = _parse_measurements(
                measurements.get("results"), start, end, now or datetime.now(UTC)
            )
            if not readings:
                raise OpenAQProviderError(
                    "OpenAQ returned no fresh PM2.5 measurements for the interval"
                )
            return readings
        finally:
            if own_client:
                await client.aclose()

    async def _get_json(
        self,
        client: httpx.AsyncClient,
        path: str,
        headers: dict[str, str],
        params: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            response = await client.get(
                f"{self.endpoint}{path}", headers=headers, params=params
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OpenAQProviderError("OpenAQ request or response failed") from exc
        if not isinstance(payload, dict):
            raise OpenAQProviderError("OpenAQ response must be a JSON object")
        return payload


def _nearest_location(
    locations: object, latitude: float, longitude: float
) -> dict[str, Any] | None:
    if not isinstance(locations, list):
        raise OpenAQProviderError("OpenAQ locations response is malformed")
    candidates = [
        location
        for location in locations
        if isinstance(location, dict)
        and isinstance(location.get("id"), int)
        and _distance_meters(location, latitude, longitude)
        <= OpenAQAirQualityAdapter.max_station_distance_meters
    ]
    return min(
        candidates,
        key=lambda location: _distance_meters(location, latitude, longitude),
        default=None,
    )


def _distance_meters(location: dict[str, Any], latitude: float, longitude: float) -> float:
    coordinates = location.get("coordinates")
    if not isinstance(coordinates, dict):
        return float("inf")
    station_latitude = coordinates.get("latitude")
    station_longitude = coordinates.get("longitude")
    if not isinstance(station_latitude, (int, float)) or not isinstance(
        station_longitude, (int, float)
    ):
        return float("inf")
    radius = 6_371_000
    delta_latitude = radians(station_latitude - latitude)
    delta_longitude = radians(station_longitude - longitude)
    value = (
        sin(delta_latitude / 2) ** 2
        + cos(radians(latitude))
        * cos(radians(station_latitude))
        * sin(delta_longitude / 2) ** 2
    )
    return radius * 2 * asin(sqrt(value))


def _select_pm25_sensor(sensors: object) -> dict[str, Any] | None:
    if not isinstance(sensors, list):
        raise OpenAQProviderError("OpenAQ sensors response is malformed")
    for sensor in sensors:
        if not isinstance(sensor, dict):
            continue
        parameter = sensor.get("parameter")
        if not isinstance(parameter, dict):
            continue
        name = str(parameter.get("name", "")).lower().replace(".", "")
        units = str(parameter.get("units", "")).replace("μ", "µ").lower()
        if name in {"pm25", "pm2_5"} and units in {"µg/m³", "ug/m3"}:
            if isinstance(sensor.get("id"), int):
                return sensor
    return None


def _parse_measurements(
    measurements: object,
    start: datetime,
    end: datetime,
    now: datetime,
) -> tuple[HourlyPM25Reading, ...]:
    if not isinstance(measurements, list):
        raise OpenAQProviderError("OpenAQ measurements response is malformed")
    readings: list[HourlyPM25Reading] = []
    for measurement in measurements:
        if not isinstance(measurement, dict):
            continue
        parameter = measurement.get("parameter")
        if not isinstance(parameter, dict):
            continue
        name = str(parameter.get("name", "")).lower().replace(".", "")
        units = str(parameter.get("units", "")).replace("μ", "µ").lower()
        value = measurement.get("value")
        timestamp = _measurement_timestamp(measurement)
        if (
            name not in {"pm25", "pm2_5"}
            or units not in {"µg/m³", "ug/m3"}
            or not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not isfinite(value)
            or value < 0
            or timestamp is None
            or not (start <= timestamp < end)
            or timestamp > now + timedelta(minutes=5)
            or now - timestamp > OpenAQAirQualityAdapter.max_reading_age
        ):
            continue
        readings.append(HourlyPM25Reading(timestamp, float(value)))
    return tuple(readings)


def _measurement_timestamp(measurement: dict[str, Any]) -> datetime | None:
    period = measurement.get("period")
    if isinstance(period, dict):
        date_from = period.get("datetimeFrom")
        if isinstance(date_from, dict):
            return _parse_timestamp(date_from.get("utc"))
    date_time = measurement.get("datetime")
    if isinstance(date_time, dict):
        return _parse_timestamp(date_time.get("utc"))
    return None


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _format_openaq_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from numbers import Real
from typing import Sequence

import httpx

from app.models.contracts import (
    Coverage,
    DataProvenance,
    DataType,
    ExposureReport,
    ReportStatus,
    RoutineRequest,
)


@dataclass(frozen=True)
class ExposureCalculation:
    """Result of calculating exposure from normalized PM2.5 readings."""

    pm25_value: float | None
    total_requested_duration: float
    usable_duration: float
    coverage_ratio: float
    coverage_percentage: float
    status: ReportStatus


@dataclass(frozen=True)
class HourlyPM25Reading:
    timestamp: datetime
    concentration: float


class OpenMeteoProviderError(Exception):
    """Raised when Open-Meteo cannot provide valid hourly PM2.5 data."""


class OpenMeteoAirQualityAdapter:
    endpoint = "https://air-quality-api.open-meteo.com/v1/air-quality"
    source_name = "Open-Meteo Air Quality API (CAMS ENSEMBLE)"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        timeout: httpx.Timeout | None = None,
    ) -> None:
        self._client = client
        self._timeout = timeout or httpx.Timeout(10.0, connect=5.0)

    async def fetch_hourly_pm25(
        self,
        latitude: float,
        longitude: float,
        start: datetime,
        end: datetime,
    ) -> tuple[HourlyPM25Reading, ...]:
        if start.tzinfo is None or end.tzinfo is None or end <= start:
            raise ValueError("start and end must be timezone-aware with end after start")

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": "pm2_5",
            "timezone": "UTC",
            "start_date": start.astimezone(UTC).date().isoformat(),
            "end_date": end.astimezone(UTC).date().isoformat(),
        }
        own_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            try:
                response = await client.get(self.endpoint, params=params)
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise OpenMeteoProviderError(
                    "Open-Meteo request or response failed"
                ) from exc
        finally:
            if own_client:
                await client.aclose()

        return _parse_hourly_pm25_payload(payload)


def _parse_hourly_pm25_payload(payload: object) -> tuple[HourlyPM25Reading, ...]:
    if not isinstance(payload, dict):
        raise OpenMeteoProviderError("Open-Meteo response must be a JSON object")
    hourly = payload.get("hourly")
    if not isinstance(hourly, dict):
        raise OpenMeteoProviderError("Open-Meteo response is missing hourly data")
    times = hourly.get("time")
    values = hourly.get("pm2_5")
    if not isinstance(times, list) or not isinstance(values, list) or len(times) != len(values):
        raise OpenMeteoProviderError("Open-Meteo hourly time and pm2_5 arrays are invalid")

    readings: list[HourlyPM25Reading] = []
    for timestamp, value in zip(times, values):
        if not isinstance(timestamp, str):
            raise OpenMeteoProviderError("Open-Meteo timestamps must be strings")
        try:
            parsed_timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise OpenMeteoProviderError("Open-Meteo returned an invalid timestamp") from exc
        if parsed_timestamp.tzinfo is None:
            parsed_timestamp = parsed_timestamp.replace(tzinfo=UTC)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, Real):
            raise OpenMeteoProviderError("Open-Meteo returned an invalid PM2.5 value")
        try:
            _validate_pm25_value(value)
        except ValueError as exc:
            raise OpenMeteoProviderError(
                "Open-Meteo returned an invalid PM2.5 value"
            ) from exc
        readings.append(
            HourlyPM25Reading(parsed_timestamp.astimezone(UTC), float(value))
        )
    return tuple(readings)


def _interval_segments(
    readings: Sequence[HourlyPM25Reading],
    start: datetime,
    end: datetime,
) -> list[tuple[float, float | None]]:
    readings_by_hour = {reading.timestamp: reading.concentration for reading in readings}
    segments: list[tuple[float, float | None]] = []
    hour_start = start.replace(minute=0, second=0, microsecond=0)
    while hour_start < end:
        hour_end = hour_start + timedelta(hours=1)
        overlap_start = max(start, hour_start)
        overlap_end = min(end, hour_end)
        if overlap_start < overlap_end:
            segments.append(
                (
                    (overlap_end - overlap_start).total_seconds() / 60,
                    readings_by_hour.get(hour_start),
                )
            )
        hour_start = hour_end
    return segments


async def create_provider_report(
    routine: RoutineRequest,
    adapter: OpenMeteoAirQualityAdapter | None = None,
    openaq_adapter: object | None = None,
    now: datetime | None = None,
) -> ExposureReport:
    """Evaluate a fully geocoded routine using Open-Meteo hourly PM2.5 data."""
    if any(stop.coordinates is None for stop in routine.stops):
        return create_unavailable_report(routine)

    start = routine.start_time or now or datetime.now(UTC)
    if start.tzinfo is None:
        raise ValueError("routine start_time must be timezone-aware")
    start = start.astimezone(UTC)
    end = start + timedelta(minutes=sum(stop.duration_minutes for stop in routine.stops))
    adapter = adapter or OpenMeteoAirQualityAdapter()
    if openaq_adapter is None:
        from app.services.openaq import (
            OpenAQAirQualityAdapter,
            OpenAQProviderError,
        )

        openaq_adapter = OpenAQAirQualityAdapter()
    else:
        from app.services.openaq import OpenAQProviderError

    durations: list[float] = []
    values: list[float | None] = []
    sources: set[str] = set()
    data_types: set[DataType] = set()
    interval_start = start
    for stop in routine.stops:
        interval_end = interval_start + timedelta(minutes=stop.duration_minutes)
        coordinates = stop.coordinates
        assert coordinates is not None
        selected_readings: Sequence[HourlyPM25Reading] = ()
        selected_source: str | None = None
        selected_type: DataType | None = None
        try:
            readings = await adapter.fetch_hourly_pm25(
                coordinates.latitude,
                coordinates.longitude,
                interval_start,
                interval_end,
            )
            if any(value is not None for _, value in _interval_segments(
                readings, interval_start, interval_end
            )):
                selected_readings = readings
                selected_source = OpenMeteoAirQualityAdapter.source_name
                selected_type = DataType.ESTIMATE
        except (OpenMeteoProviderError, httpx.HTTPError):
            pass

        if selected_source is None:
            try:
                readings = await openaq_adapter.fetch_pm25(
                    coordinates.latitude,
                    coordinates.longitude,
                    interval_start,
                    interval_end,
                    now=now,
                )
                if readings:
                    selected_readings = readings
                    selected_source = "OpenAQ ground-monitor measurement"
                    selected_type = DataType.OBSERVATION
            except (OpenAQProviderError, httpx.HTTPError):
                selected_readings = ()

        for duration, value in _interval_segments(
            selected_readings, interval_start, interval_end
        ):
            durations.append(duration)
            values.append(value)
        if selected_source is not None and selected_type is not None:
            sources.add(selected_source)
            data_types.add(selected_type)
        interval_start = interval_end

    calculation = calculate_exposure(durations, values)
    if calculation.status is ReportStatus.UNAVAILABLE:
        return create_unavailable_report(
            routine,
            message="Open-Meteo returned no usable PM2.5 readings for this routine.",
            error_code="NO_USABLE_PM25_DATA",
        )
    return ExposureReport(
        status=ReportStatus.AVAILABLE,
        pm25_value=calculation.pm25_value,
        provenance=DataProvenance(
            source="; ".join(sorted(sources)),
            data_type=next(iter(data_types)) if len(data_types) == 1 else DataType.UNKNOWN,
            sources=sorted(sources),
            data_types=sorted(data_types, key=lambda item: item.value),
            timestamp=end,
        ),
        coverage=Coverage(
            usable_duration_minutes=calculation.usable_duration,
            total_requested_duration_minutes=calculation.total_requested_duration,
            ratio=calculation.coverage_ratio,
            percentage=calculation.coverage_percentage,
        ),
        message=(
            "Exposure calculated from source-validated PM2.5 readings. "
            "Modelled estimates and ground-monitor measurements are identified "
            "separately in provenance."
        ),
    )


def _provider_error_report(routine: RoutineRequest) -> ExposureReport:
    return create_unavailable_report(
        routine,
        message="Open-Meteo PM2.5 data is temporarily unavailable.",
        error_code="PROVIDER_ERROR",
    )


def calculate_exposure(
    durations: Sequence[float],
    pm25_values: Sequence[float | None],
) -> ExposureCalculation:
    """Calculate a duration-weighted mean from PM2.5 concentrations.

    ``pm25_values`` contains normalized PM2.5 concentrations in µg/m³.
    Missing values are represented by ``None`` and are excluded from the
    weighted mean while their durations remain part of the requested total.
    """
    if len(durations) != len(pm25_values):
        raise ValueError("durations and pm25_values must have the same length")
    if not durations:
        raise ValueError("at least one duration is required")

    total_requested_duration = 0.0
    usable_duration = 0.0
    weighted_total = 0.0

    for duration, pm25_value in zip(durations, pm25_values):
        _validate_duration(duration)
        total_requested_duration += duration

        if pm25_value is None:
            continue
        _validate_pm25_value(pm25_value)
        usable_duration += duration
        weighted_total += pm25_value * duration

    coverage_ratio = usable_duration / total_requested_duration
    status = (
        ReportStatus.AVAILABLE
        if usable_duration > 0
        else ReportStatus.UNAVAILABLE
    )
    return ExposureCalculation(
        pm25_value=weighted_total / usable_duration if usable_duration > 0 else None,
        total_requested_duration=total_requested_duration,
        usable_duration=usable_duration,
        coverage_ratio=coverage_ratio,
        coverage_percentage=coverage_ratio * 100,
        status=status,
    )


def _validate_duration(duration: float) -> None:
    if (
        isinstance(duration, bool)
        or not isinstance(duration, Real)
        or not isfinite(duration)
        or duration <= 0
    ):
        raise ValueError("durations must be finite numbers greater than zero")


def _validate_pm25_value(pm25_value: float) -> None:
    if (
        isinstance(pm25_value, bool)
        or not isinstance(pm25_value, Real)
        or not isfinite(pm25_value)
        or pm25_value < 0
    ):
        raise ValueError("PM2.5 concentrations must be finite numbers at least zero")


def create_unavailable_report(
    routine: RoutineRequest,
    message: str = "Air-quality provider integration is not available yet.",
    error_code: str = "PROVIDER_NOT_IMPLEMENTED",
) -> ExposureReport:
    total_duration = sum(stop.duration_minutes for stop in routine.stops)
    return ExposureReport(
        status=ReportStatus.UNAVAILABLE,
        provenance=DataProvenance(data_type=DataType.UNKNOWN),
        coverage=Coverage(
            usable_duration_minutes=0,
            total_requested_duration_minutes=total_duration,
            ratio=0,
            percentage=0,
        ),
        message=message,
        error_code=error_code,
    )

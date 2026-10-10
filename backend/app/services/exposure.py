from dataclasses import dataclass
from math import isfinite
from numbers import Real
from typing import Sequence

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


def create_unavailable_report(routine: RoutineRequest) -> ExposureReport:
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
        message="Air-quality provider integration is not available yet.",
        error_code="PROVIDER_NOT_IMPLEMENTED",
    )

import math

import pytest

from app.models.contracts import ReportStatus
from app.services.exposure import calculate_exposure


def test_calculates_duration_weighted_pm25_mean() -> None:
    result = calculate_exposure([2, 8], [100, 25])

    assert result.pm25_value == pytest.approx(40)
    assert result.total_requested_duration == pytest.approx(10)
    assert result.usable_duration == pytest.approx(10)
    assert result.coverage_ratio == pytest.approx(1)
    assert result.coverage_percentage == pytest.approx(100)
    assert result.status is ReportStatus.AVAILABLE


def test_excludes_missing_readings_from_mean_but_tracks_their_duration() -> None:
    result = calculate_exposure([2, 8], [100, None])

    assert result.pm25_value == pytest.approx(100)
    assert result.total_requested_duration == pytest.approx(10)
    assert result.usable_duration == pytest.approx(2)
    assert result.coverage_ratio == pytest.approx(0.2)
    assert result.coverage_percentage == pytest.approx(20)
    assert result.status is ReportStatus.AVAILABLE


def test_returns_unavailable_when_all_readings_are_missing() -> None:
    result = calculate_exposure([2, 8], [None, None])

    assert result.pm25_value is None
    assert result.total_requested_duration == pytest.approx(10)
    assert result.usable_duration == 0
    assert result.coverage_ratio == 0
    assert result.coverage_percentage == 0
    assert result.status is ReportStatus.UNAVAILABLE


@pytest.mark.parametrize(
    "durations", [[0], [-1], [math.inf], [math.nan], ["not-a-duration"]]
)
def test_rejects_invalid_durations(durations: list[object]) -> None:
    with pytest.raises(ValueError, match="durations"):
        calculate_exposure(durations, [25])


@pytest.mark.parametrize(
    "pm25_value", [-1, math.inf, -math.inf, math.nan, "not-a-concentration"]
)
def test_rejects_invalid_pm25_values(pm25_value: object) -> None:
    with pytest.raises(ValueError, match="PM2.5"):
        calculate_exposure([1], [pm25_value])


def test_rejects_mismatched_segments() -> None:
    with pytest.raises(ValueError, match="same length"):
        calculate_exposure([1, 2], [25])


def test_rejects_empty_segments() -> None:
    with pytest.raises(ValueError, match="at least one"):
        calculate_exposure([], [])

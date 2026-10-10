from app.models.contracts import (
    Coverage,
    DataProvenance,
    DataType,
    ExposureReport,
    ReportStatus,
    RoutineRequest,
)


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


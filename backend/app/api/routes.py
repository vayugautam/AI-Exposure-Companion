from fastapi import APIRouter

from app.models.contracts import (
    ExposureReport,
    ExposureRequest,
    HealthResponse,
    MockExposureResponse,
    RoutineRequest,
)
from app.services.exposure import create_unavailable_report

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.post(
    "/api/v1/exposure",
    response_model=MockExposureResponse,
    tags=["exposure"],
    summary="Accept a mobile exposure request (mock response)",
)
def create_mock_exposure(request: ExposureRequest) -> MockExposureResponse:
    """Validate the mobile payload without querying a provider or estimating exposure."""
    return MockExposureResponse(
        user_id=request.user.user_id,
        places_received=len(request.places),
        total_requested_duration_minutes=sum(
            place.duration_minutes for place in request.places
        ),
        message=(
            "Mock response only: no air-quality provider was queried and no exposure "
            "estimate was calculated."
        ),
        warnings=[
            "PM2.5 readings, coverage, and exposure estimates are not available yet."
        ],
    )


@router.post(
    "/v1/exposure/reports",
    response_model=ExposureReport,
    tags=["exposure"],
    summary="Create an exposure report",
)
def create_exposure_report(routine: RoutineRequest) -> ExposureReport:
    return create_unavailable_report(routine)


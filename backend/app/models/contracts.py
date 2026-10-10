from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_STOPS = 20
MAX_LABEL_LENGTH = 120
MAX_ROUTINE_NAME_LENGTH = 120
MAX_USER_ID_LENGTH = 128


class DataType(StrEnum):
    OBSERVATION = "observation"
    FORECAST = "forecast"
    ESTIMATE = "estimate"
    UNKNOWN = "unknown"


class ReportStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(description="Service liveness status.")


class ExposureUser(BaseModel):
    """Minimal, non-sensitive user identifier supplied by the mobile client."""

    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, max_length=MAX_USER_ID_LENGTH)
    name: str | None = Field(default=None, min_length=1, max_length=MAX_LABEL_LENGTH)

    @field_validator("user_id", "name")
    @classmethod
    def validate_non_blank_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("value must not be blank")
        return value


class ExposurePlace(BaseModel):
    """A named location and the time spent there, as sent by the mobile app."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    name: str = Field(min_length=1, max_length=MAX_LABEL_LENGTH)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    duration_minutes: float = Field(gt=0, le=24 * 60)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must not be blank")
        return value


class ExposureRequest(BaseModel):
    """Input contract for the mobile exposure request endpoint."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    user: ExposureUser
    places: list[ExposurePlace] = Field(min_length=1, max_length=MAX_STOPS)


class MockExposureResponse(BaseModel):
    """Temporary response until a PM2.5 provider and estimator are implemented."""

    model_config = ConfigDict(extra="forbid")

    status: str = "mock"
    mock: bool = True
    user_id: str
    places_received: int = Field(ge=1)
    total_requested_duration_minutes: float = Field(gt=0)
    message: str
    warnings: list[str]


class Coordinates(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    latitude: float = Field(ge=-90, le=90, description="Latitude in decimal degrees.")
    longitude: float = Field(ge=-180, le=180, description="Longitude in decimal degrees.")


class RoutineStop(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    label: str = Field(min_length=1, max_length=MAX_LABEL_LENGTH)
    duration_minutes: float = Field(
        gt=0,
        le=24 * 60,
        description="Time spent at this stop, in minutes.",
    )
    coordinates: Coordinates | None = None

    @field_validator("label")
    @classmethod
    def validate_label(cls, label: str) -> str:
        if not label.strip():
            raise ValueError("label must not be blank")
        return label


class RoutineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    name: str = Field(default="Untitled routine", min_length=1, max_length=MAX_ROUTINE_NAME_LENGTH)
    stops: list[RoutineStop] = Field(min_length=1, max_length=MAX_STOPS)
    start_time: datetime | None = Field(
        default=None,
        description="UTC start time for evaluating the routine; defaults to now.",
    )

    @field_validator("start_time")
    @classmethod
    def validate_start_time_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("start_time must include a timezone")
        return value

    @field_validator("stops")
    @classmethod
    def validate_total_duration(cls, stops: list[RoutineStop]) -> list[RoutineStop]:
        total = sum(stop.duration_minutes for stop in stops)
        if total > 7 * 24 * 60:
            raise ValueError("total requested duration must be at most 10080 minutes")
        return stops


class DataProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime | None = Field(
        default=None,
        description="Timestamp of the source data in UTC, when available.",
    )
    source: str | None = Field(
        default=None,
        max_length=MAX_LABEL_LENGTH,
        description="Human-readable data source, when available.",
    )
    data_type: DataType = DataType.UNKNOWN
    sources: list[str] = Field(default_factory=list)
    data_types: list[DataType] = Field(default_factory=list)


class Coverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    usable_duration_minutes: float = Field(ge=0)
    total_requested_duration_minutes: float = Field(gt=0)
    ratio: float = Field(ge=0, le=1)
    percentage: float = Field(ge=0, le=100)


class ExposureReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ReportStatus
    pm25_value: float | None = Field(
        default=None,
        ge=0,
        description="Duration-weighted PM2.5 concentration, in µg/m³.",
    )
    pm25_unit: str = Field(default="µg/m³", min_length=1, max_length=20)
    provenance: DataProvenance
    coverage: Coverage
    message: str = Field(min_length=1, max_length=500)
    error_code: str | None = Field(default=None, max_length=80)

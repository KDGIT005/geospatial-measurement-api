"""Pydantic v2 schemas for request validation and response serialisation.

Separated from the ORM models so that the API contract is explicit and
decoupled from the database schema.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# File responses
# ---------------------------------------------------------------------------


class FileResponse(BaseModel):
    """Returned by POST /api/files/ on successful upload."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    feature_count: int | None = None
    crs: str | None = None
    status: str

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "b3f1c2e4-1234-5678-abcd-ef0123456789",
                "filename": "survey.kml",
                "feature_count": 120,
                "crs": "EPSG:4326",
                "status": "COMPLETED",
            }
        },
    )


class FileDetailResponse(FileResponse):
    """Returned by GET /api/files/{id}/ with extra metadata."""

    file_type: str
    created_at: datetime
    error_message: str | None = None
    measured_feature_count: int = 0
    unsupported_feature_count: int = 0


# ---------------------------------------------------------------------------
# Measurement responses
# ---------------------------------------------------------------------------


class MeasurementDetail(BaseModel):
    """The measurement block inside a feature result."""

    type: str  # "area" or "length"
    value: float
    unit: str  # "square_meters" or "meters"
    projected_crs: str
    geodesic_value: float | None = None
    method: str  # always "projected_utm"


class FeatureMeasurementResponse(BaseModel):
    """One feature inside the measurements list."""

    feature_index: int
    geometry_type: str | None = None
    crs: str | None = None
    properties: dict | None = None
    geometry: dict | None = None
    measurement: MeasurementDetail | None = None
    supported: bool = True
    note: str | None = None


class MeasurementsResponse(BaseModel):
    """Paginated measurement results for a file."""

    file_id: str
    crs: str | None = None
    total: int
    limit: int
    offset: int
    features: list[FeatureMeasurementResponse]


# ---------------------------------------------------------------------------
# Error response (for OpenAPI docs)
# ---------------------------------------------------------------------------


class ErrorResponse(BaseModel):
    """Standard error body returned by all error handlers."""

    detail: str
    code: str

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "detail": "Missing or unparseable CRS (.prj file)",
                "code": "MISSING_CRS",
            }
        },
    )


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str = Field(default="ok", examples=["ok"])

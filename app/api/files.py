"""Thin route layer for the /api/files endpoints.

Routes validate input, call services, and return responses.
No business logic lives here — only orchestration.
"""

import logging

from fastapi import APIRouter, Depends, Query, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session
from starlette.status import HTTP_201_CREATED

from app.config import settings
from app.core.exceptions import GeoFileNotFoundError
from app.database import get_db
from app.models import Feature, File
from app.schemas import (
    ErrorResponse,
    FeatureMeasurementResponse,
    FileDetailResponse,
    FileResponse,
    MeasurementDetail,
    MeasurementsResponse,
)
from app.services.file_ingest import (
    IngestContext,
    detect_file_type,
    read_kml,
    read_shapefile,
    save_upload_stream,
    validate_and_extract_zip,
)
from app.services.measurements import compute_measurement

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/",
    status_code=HTTP_201_CREATED,
    response_model=FileResponse,
    summary="Upload a geospatial file",
    description="Upload a KML or zipped Shapefile. The file is processed synchronously.",
    responses={
        400: {"model": ErrorResponse, "description": "Corrupt or invalid file"},
        413: {"model": ErrorResponse, "description": "File too large"},
        415: {"model": ErrorResponse, "description": "Unsupported file type"},
        422: {"model": ErrorResponse, "description": "Missing CRS"},
    },
)
async def upload_file(
    file: UploadFile,
    db: Session = Depends(get_db),
) -> FileResponse:
    """Accept a geospatial file, extract features, compute measurements."""
    filename = file.filename or "unknown"
    file_type = detect_file_type(filename)

    # Create the file record (PENDING)
    file_record = File(filename=filename, file_type=file_type, status="PENDING")
    db.add(file_record)
    db.commit()
    db.refresh(file_record)

    file_id = file_record.id
    logger.info("Processing file %s (id=%s, type=%s)", filename, file_id, file_type)

    with IngestContext() as ctx:
        try:
            # --- PROCESSING ---
            file_record.status = "PROCESSING"
            db.commit()

            # Save upload to temp dir (stream-checks size limit)
            upload_path = ctx.temp_dir / filename
            await save_upload_stream(file, upload_path)

            # Read features based on file type
            if file_type == "kml":
                features, crs = read_kml(upload_path)
            else:
                # Extract zip and read shapefile
                extract_dir = ctx.temp_dir / "extracted"
                extract_dir.mkdir()
                shp_path = validate_and_extract_zip(upload_path, extract_dir)
                features, crs = read_shapefile(shp_path)

            # Compute measurements for each feature
            feature_models = []
            for feat in features:
                measurement = {}
                if feat["is_supported"] and feat["geometry"] is not None:
                    measurement = compute_measurement(feat["geometry"], crs)
                else:
                    measurement = {
                        "measurement_type": None,
                        "measurement_value": None,
                        "measurement_unit": None,
                        "projected_crs": None,
                        "geodesic_value": None,
                        "method": None,
                        "is_supported": feat["is_supported"],
                        "note": feat.get("note"),
                    }

                feature_models.append(
                    Feature(
                        file_id=file_id,
                        feature_index=feat["feature_index"],
                        geometry_type=feat["geometry_type"],
                        geometry=feat["geometry"],
                        crs=feat["crs"],
                        properties=feat["properties"],
                        is_supported=measurement.get("is_supported", feat["is_supported"]),
                        is_valid=feat.get("is_valid"),
                        measurement_type=measurement.get("measurement_type"),
                        measurement_value=measurement.get("measurement_value"),
                        measurement_unit=measurement.get("measurement_unit"),
                        projected_crs=measurement.get("projected_crs"),
                        geodesic_value=measurement.get("geodesic_value"),
                        method=measurement.get("method"),
                        note=measurement.get("note") or feat.get("note"),
                    )
                )

            # Bulk insert all features
            db.add_all(feature_models)

            # Update file record
            file_record.crs = crs
            file_record.feature_count = len(features)
            file_record.status = "COMPLETED"
            db.commit()

            logger.info("File %s processed: %d features", file_id, len(features))

        except Exception as exc:
            # Roll back any partial changes
            db.rollback()

            # Update file record to FAILED
            file_record.status = "FAILED"
            file_record.error_message = str(exc)
            db.commit()

            logger.error("Failed to process file %s: %s", file_id, exc)
            raise  # Re-raise so the exception handler sends the proper HTTP error

    return FileResponse.model_validate(file_record)


@router.get(
    "/{file_id}/",
    response_model=FileDetailResponse,
    summary="Get file info",
    description="Returns file metadata including feature counts.",
    responses={404: {"model": ErrorResponse, "description": "File not found"}},
)
def get_file(
    file_id: str,
    db: Session = Depends(get_db),
) -> FileDetailResponse:
    """Return detailed info about an uploaded file."""
    file_record = db.query(File).filter(File.id == file_id).first()
    if file_record is None:
        raise GeoFileNotFoundError(f"File with id '{file_id}' not found.")

    # Count measured vs unsupported features
    measured_count = (
        db.query(func.count(Feature.id))
        .filter(Feature.file_id == file_id, Feature.measurement_value.isnot(None))
        .scalar()
    )
    unsupported_count = (
        db.query(func.count(Feature.id))
        .filter(Feature.file_id == file_id, Feature.is_supported.is_(False))
        .scalar()
    )

    return FileDetailResponse(
        id=file_record.id,
        filename=file_record.filename,
        file_type=file_record.file_type,
        feature_count=file_record.feature_count,
        crs=file_record.crs,
        status=file_record.status,
        created_at=file_record.created_at,
        error_message=file_record.error_message,
        measured_feature_count=measured_count or 0,
        unsupported_feature_count=unsupported_count or 0,
    )


@router.get(
    "/{file_id}/measurements/",
    response_model=MeasurementsResponse,
    summary="Get feature measurements",
    description="Returns paginated measurements for every feature in the file.",
    responses={404: {"model": ErrorResponse, "description": "File not found"}},
)
def get_measurements(
    file_id: str,
    limit: int = Query(
        default=settings.DEFAULT_PAGE_LIMIT,
        ge=1,
        le=settings.MAX_PAGE_LIMIT,
        description="Max features per page",
    ),
    offset: int = Query(default=0, ge=0, description="Number of features to skip"),
    include_geometry: bool = Query(
        default=True, description="Include GeoJSON geometry in response"
    ),
    db: Session = Depends(get_db),
) -> MeasurementsResponse:
    """Return paginated measurements for all features in a file."""
    file_record = db.query(File).filter(File.id == file_id).first()
    if file_record is None:
        raise GeoFileNotFoundError(f"File with id '{file_id}' not found.")

    # Total feature count
    total = db.query(func.count(Feature.id)).filter(Feature.file_id == file_id).scalar()

    # Paginated query, ordered by feature_index
    features_query = (
        db.query(Feature)
        .filter(Feature.file_id == file_id)
        .order_by(Feature.feature_index)
        .offset(offset)
        .limit(limit)
        .all()
    )

    feature_responses = []
    for feat in features_query:
        # Build measurement detail if there is a measurement
        measurement = None
        if feat.measurement_type is not None:
            measurement = MeasurementDetail(
                type=feat.measurement_type,
                value=feat.measurement_value,
                unit=feat.measurement_unit,
                projected_crs=feat.projected_crs,
                geodesic_value=feat.geodesic_value,
                method=feat.method,
            )

        feature_responses.append(
            FeatureMeasurementResponse(
                feature_index=feat.feature_index,
                geometry_type=feat.geometry_type,
                crs=feat.crs,
                properties=feat.properties,
                geometry=feat.geometry if include_geometry else None,
                measurement=measurement,
                supported=feat.is_supported,
                note=feat.note,
            )
        )

    return MeasurementsResponse(
        file_id=file_id,
        crs=file_record.crs,
        total=total or 0,
        limit=limit,
        offset=offset,
        features=feature_responses,
    )

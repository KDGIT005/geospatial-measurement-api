"""SQLAlchemy ORM models for the files and features tables.

Design notes:
- JSON columns use sqlalchemy.JSON directly (works on both SQLite and Postgres).
- Features are bulk-inserted per file, not one commit per feature.
- Composite index on (file_id, feature_index) for ordered paginated queries.
- Cascade delete: removing a file removes all its features.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class File(Base):
    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)  # "kml" or "shapefile"
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    crs: Mapped[str | None] = mapped_column(String(255), nullable=True)
    feature_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )

    features: Mapped[list["Feature"]] = relationship(
        back_populates="file", cascade="all, delete-orphan"
    )


class Feature(Base):
    __tablename__ = "features"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("files.id", ondelete="CASCADE"), nullable=False
    )
    feature_index: Mapped[int] = mapped_column(Integer, nullable=False)
    geometry_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    geometry: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    crs: Mapped[str | None] = mapped_column(String(255), nullable=True)
    properties: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_supported: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_valid: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    measurement_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    measurement_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    measurement_unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    projected_crs: Mapped[str | None] = mapped_column(String(50), nullable=True)
    geodesic_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    method: Mapped[str | None] = mapped_column(String(30), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    file: Mapped["File"] = relationship(back_populates="features")

    __table_args__ = (Index("ix_features_file_id_feature_index", "file_id", "feature_index"),)

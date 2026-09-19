"""Modelo persistente da importação; independente do layout HTTP."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_uuid() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    source_sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    sheet_name: Mapped[str] = mapped_column(String(255), nullable=False)
    declared_dimension: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed")
    package_count: Mapped[int] = mapped_column(Integer, nullable=False)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False)
    analysis: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    routes: Mapped[list["Route"]] = relationship(
        back_populates="import_batch", cascade="all, delete-orphan", order_by="Route.external_id"
    )


class Route(Base):
    __tablename__ = "routes"
    __table_args__ = (UniqueConstraint("import_batch_id", "external_id", name="uq_route_import_external"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    import_batch_id: Mapped[str] = mapped_column(
        ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="imported")
    package_count: Mapped[int] = mapped_column(Integer, nullable=False)
    original_stop_count: Mapped[int] = mapped_column(Integer, nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    import_batch: Mapped[ImportBatch] = relationship(back_populates="routes")
    packages: Mapped[list["Package"]] = relationship(
        back_populates="route", cascade="all, delete-orphan", order_by="Package.source_row"
    )


class Package(Base):
    __tablename__ = "packages"
    __table_args__ = (
        UniqueConstraint("import_batch_id", "tracking_id", name="uq_package_import_tracking"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    import_batch_id: Mapped[str] = mapped_column(
        ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    route_id: Mapped[str] = mapped_column(ForeignKey("routes.id", ondelete="CASCADE"), nullable=False, index=True)
    tracking_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_row: Mapped[int] = mapped_column(Integer, nullable=False)
    original_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    original_stop: Mapped[int | None] = mapped_column(Integer, nullable=True)
    address: Mapped[str] = mapped_column(String(1000), nullable=False)
    neighborhood: Mapped[str] = mapped_column(String(255), nullable=False)
    city: Mapped[str] = mapped_column(String(255), nullable=False)
    postal_code: Mapped[str] = mapped_column(String(32), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    street_key: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    route: Mapped[Route] = relationship(back_populates="packages")

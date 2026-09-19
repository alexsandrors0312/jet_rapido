"""Contratos HTTP separados das entidades do banco."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RouteSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    import_batch_id: str
    external_id: str
    status: str
    package_count: int
    original_stop_count: int
    reviewed_at: datetime | None


class PackageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    tracking_id: str
    source_row: int
    original_sequence: int | None
    original_stop: int | None
    address: str
    neighborhood: str
    city: str
    postal_code: str
    latitude: float
    longitude: float
    street_key: str
    status: str


class RouteResponse(RouteSummary):
    packages: list[PackageResponse]


class ImportResponse(BaseModel):
    id: str
    source_sha256: str
    source_filename: str
    status: str
    package_count: int
    warning_count: int
    warnings: list[dict]
    split_streets: list[dict]
    routes: list[RouteSummary]
    created_at: datetime
    idempotent: bool = False


class RouteReviewRequest(BaseModel):
    reviewed: bool = True


class HealthResponse(BaseModel):
    status: str

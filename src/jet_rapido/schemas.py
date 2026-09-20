"""Contratos HTTP separados das entidades do banco."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    delivery_point_id: str
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
    geographic_issues: list[dict]
    routes: list[RouteSummary]
    created_at: datetime
    idempotent: bool = False


class RouteReviewRequest(BaseModel):
    reviewed: bool = True


class DeliveryPointResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    route_id: str
    address_key: str
    original_address: str
    original_neighborhood: str
    original_city: str
    original_postal_code: str
    imported_latitude: float
    imported_longitude: float
    effective_latitude: float
    effective_longitude: float
    review_status: str
    revision: int
    review_source: str | None
    review_note: str | None
    reviewed_at: datetime | None
    package_count: int
    created_at: datetime
    updated_at: datetime


class DeliveryPointReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    expected_revision: int | None = Field(default=None, ge=1)
    review_status: Literal["confirmed", "corrected", "rejected"]
    review_source: Literal["operator", "driver", "map"] = "operator"
    review_note: str | None = Field(default=None, max_length=2000)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def validate_coordinates(self):
        has_both = self.latitude is not None and self.longitude is not None
        has_any = self.latitude is not None or self.longitude is not None
        if self.review_status == "corrected" and not has_both:
            raise ValueError("Uma correção exige latitude e longitude.")
        if self.review_status != "corrected" and has_any:
            raise ValueError("Coordenadas só podem ser informadas em uma correção.")
        return self


class DeliveryPointConfirmationResponse(BaseModel):
    confirmed_count: int
    points: list[DeliveryPointResponse]


class WalkingMatrixCreateRequest(BaseModel):
    allow_unreviewed: bool = False


class WalkingMatrixResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    route_id: str
    provider: str
    profile: str
    quality: str
    input_hash: str
    input_snapshot: dict | None
    stale: bool = False
    point_count: int
    reachable_pairs: int
    unreachable_pairs: int
    dataset_version: str | None
    created_at: datetime
    idempotent: bool = False


class WalkingMatrixEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    origin_delivery_point_id: str
    destination_delivery_point_id: str
    distance_m: float | None
    duration_s: float | None
    reachable: bool
    error_code: str | None


class HealthResponse(BaseModel):
    status: str


class DeliveryPointReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    revision: int
    before: dict
    after: dict
    created_at: datetime

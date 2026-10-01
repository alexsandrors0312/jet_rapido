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


class MacroPlanCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    walking_matrix_id: str
    max_packages: int = Field(default=8, ge=1, le=200)
    max_pairwise_m: float = Field(default=400, gt=0)
    max_base_roundtrip_m: float = Field(default=600, gt=0)


class MacroStopReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_status: Literal["accepted", "rejected"]
    review_note: str | None = Field(default=None, max_length=2000)


class MacroStopResponse(BaseModel):
    id: str
    ordinal: int
    candidate_base_point_id: str
    candidate_base_address: str
    parking_status: Literal["unverified"]
    delivery_point_ids: list[str]
    delivery_point_count: int
    street_count: int
    stop_type: Literal["multi_address_walk_candidate", "single_address_stop"]
    package_count: int
    original_stops: list[int]
    max_pairwise_m: float
    max_base_roundtrip_m: float
    review_status: Literal["pending", "accepted", "rejected"]
    review_note: str | None
    reviewed_at: datetime | None


class MacroPlanResponse(BaseModel):
    id: str
    route_id: str
    walking_matrix_id: str
    input_hash: str
    created_at: datetime
    stale: bool
    idempotent: bool = False
    max_packages: int
    max_pairwise_m: float
    max_base_roundtrip_m: float
    package_count: int
    point_count: int
    exact_coverage: bool
    original_stop_count: int
    packages_without_original_stop: int
    original_stops_split: int
    macro_stop_count: int
    multi_address_stop_count: int
    single_address_stop_count: int
    cross_street_stop_count: int
    packages_in_multi_address_stops: int
    distance_comparison_available: bool
    distance_comparison_note: str
    stops: list[MacroStopResponse]


class DeliveryPointReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    revision: int
    before: dict
    after: dict
    created_at: datetime

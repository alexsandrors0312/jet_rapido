"""Configuração explícita e injetável da aplicação."""

from dataclasses import dataclass
import os
from math import isfinite


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///data/jet_rapido.db"
    max_upload_bytes: int = 5 * 1024 * 1024
    max_xlsx_uncompressed_bytes: int = 50 * 1024 * 1024
    max_xlsx_entries: int = 1_000
    map_provider: str = "straight_line"
    max_matrix_points: int = 200
    osrm_base_url: str = "http://localhost:5000"
    osrm_profile: str = "foot"
    osrm_timeout_seconds: float = 20.0
    osrm_block_size: int = 50
    osrm_dataset_revision: str = "unverified"
    osrm_snap_radius_m: float = 50.0
    straight_line_detour_factor: float = 1.25
    walking_speed_mps: float = 1.3

    def __post_init__(self) -> None:
        if not self.database_url.strip():
            raise ValueError("DATABASE_URL não pode ser vazia.")
        for name in (
            "max_upload_bytes", "max_xlsx_uncompressed_bytes", "max_xlsx_entries",
            "max_matrix_points", "osrm_block_size",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} deve ser positivo.")
        for name in ("osrm_timeout_seconds", "straight_line_detour_factor", "walking_speed_mps", "osrm_snap_radius_m"):
            if not isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f"{name} deve ser positivo.")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv("DATABASE_URL", cls.database_url),
            max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", cls.max_upload_bytes)),
            max_xlsx_uncompressed_bytes=int(
                os.getenv("MAX_XLSX_UNCOMPRESSED_BYTES", cls.max_xlsx_uncompressed_bytes)
            ),
            max_xlsx_entries=int(os.getenv("MAX_XLSX_ENTRIES", cls.max_xlsx_entries)),
            map_provider=os.getenv("MAP_PROVIDER", cls.map_provider),
            max_matrix_points=int(os.getenv("MAX_MATRIX_POINTS", cls.max_matrix_points)),
            osrm_base_url=os.getenv("OSRM_BASE_URL", cls.osrm_base_url),
            osrm_profile=os.getenv("OSRM_PROFILE", cls.osrm_profile),
            osrm_timeout_seconds=float(os.getenv("OSRM_TIMEOUT_SECONDS", cls.osrm_timeout_seconds)),
            osrm_block_size=int(os.getenv("OSRM_BLOCK_SIZE", cls.osrm_block_size)),
            osrm_dataset_revision=os.getenv("OSRM_DATASET_REVISION", cls.osrm_dataset_revision),
            osrm_snap_radius_m=float(os.getenv("OSRM_SNAP_RADIUS_M", cls.osrm_snap_radius_m)),
            straight_line_detour_factor=float(
                os.getenv("STRAIGHT_LINE_DETOUR_FACTOR", cls.straight_line_detour_factor)
            ),
            walking_speed_mps=float(os.getenv("WALKING_SPEED_MPS", cls.walking_speed_mps)),
        )

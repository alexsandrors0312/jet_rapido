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
    # Provedor veicular separado do pedestre. Sem configuração explícita, a ordem
    # veicular é recusada em vez de cair em custo pedestre ou em linha reta. O
    # conjunto de dados `car` precisa ser extraído com o perfil veicular: chamar
    # um extrato pedestre com `/driving` não muda os custos.
    vehicle_map_provider: str = "unconfigured"
    vehicle_osrm_base_url: str = ""
    vehicle_osrm_profile: str = "car"
    vehicle_osrm_timeout_seconds: float = 20.0
    vehicle_osrm_block_size: int = 50
    vehicle_osrm_dataset_revision: str = "unverified"
    vehicle_osrm_snap_radius_m: float = 100.0
    vehicle_exact_base_limit: int = 12

    def __post_init__(self) -> None:
        if not self.database_url.strip():
            raise ValueError("DATABASE_URL não pode ser vazia.")
        # Normaliza tipos para que a identidade de cache não dependa de o chamador
        # ter passado 50 ou 50.0: o `cache_key` do provedor usa a representação
        # textual do raio e da revisão.
        for name in (
            "max_upload_bytes", "max_xlsx_uncompressed_bytes", "max_xlsx_entries",
            "max_matrix_points", "osrm_block_size", "vehicle_osrm_block_size",
            "vehicle_exact_base_limit",
        ):
            object.__setattr__(self, name, int(getattr(self, name)))
        for name in (
            "osrm_timeout_seconds", "straight_line_detour_factor", "walking_speed_mps",
            "osrm_snap_radius_m", "vehicle_osrm_timeout_seconds", "vehicle_osrm_snap_radius_m",
        ):
            object.__setattr__(self, name, float(getattr(self, name)))
        for name in (
            "max_upload_bytes", "max_xlsx_uncompressed_bytes", "max_xlsx_entries",
            "max_matrix_points", "osrm_block_size", "vehicle_osrm_block_size",
            "vehicle_exact_base_limit",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} deve ser positivo.")
        for name in (
            "osrm_timeout_seconds", "straight_line_detour_factor", "walking_speed_mps",
            "osrm_snap_radius_m", "vehicle_osrm_timeout_seconds", "vehicle_osrm_snap_radius_m",
        ):
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
            vehicle_map_provider=os.getenv("VEHICLE_MAP_PROVIDER", cls.vehicle_map_provider),
            vehicle_osrm_base_url=os.getenv("VEHICLE_OSRM_BASE_URL", cls.vehicle_osrm_base_url),
            vehicle_osrm_profile=os.getenv("VEHICLE_OSRM_PROFILE", cls.vehicle_osrm_profile),
            vehicle_osrm_timeout_seconds=float(
                os.getenv("VEHICLE_OSRM_TIMEOUT_SECONDS", cls.vehicle_osrm_timeout_seconds)
            ),
            vehicle_osrm_block_size=int(
                os.getenv("VEHICLE_OSRM_BLOCK_SIZE", cls.vehicle_osrm_block_size)
            ),
            vehicle_osrm_dataset_revision=os.getenv(
                "VEHICLE_OSRM_DATASET_REVISION", cls.vehicle_osrm_dataset_revision
            ),
            vehicle_osrm_snap_radius_m=float(
                os.getenv("VEHICLE_OSRM_SNAP_RADIUS_M", cls.vehicle_osrm_snap_radius_m)
            ),
            vehicle_exact_base_limit=int(
                os.getenv("VEHICLE_EXACT_BASE_LIMIT", cls.vehicle_exact_base_limit)
            ),
        )

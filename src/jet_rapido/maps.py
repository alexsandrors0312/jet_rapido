"""Provedores intercambiáveis de matriz pedestre."""

from dataclasses import dataclass
from hashlib import sha256
from math import isfinite
import re
from typing import Protocol
from urllib.parse import quote

import httpx2 as httpx

from .config import Settings
from .geography import haversine_meters


class MapProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class MatrixPoint:
    id: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class MatrixCell:
    origin_id: str
    destination_id: str
    distance_m: float | None
    duration_s: float | None
    reachable: bool
    error_code: str | None = None


@dataclass(frozen=True)
class MatrixComputation:
    provider: str
    profile: str
    quality: str
    cells: tuple[MatrixCell, ...]
    dataset_version: str | None = None


class WalkingMatrixProvider(Protocol):
    name: str
    profile: str
    quality: str

    def compute(self, points: list[MatrixPoint]) -> MatrixComputation: ...


class StraightLineWalkingProvider:
    """Estimativa local para desenvolvimento; não representa acessos ou barreiras."""

    name = "straight_line"
    profile = "walking_estimate"
    quality = "estimate_only"

    def __init__(self, *, detour_factor: float = 1.25, walking_speed_mps: float = 1.3):
        self.detour_factor = detour_factor
        self.walking_speed_mps = walking_speed_mps

    @property
    def cache_key(self) -> str:
        return f"straight-v2:{self.detour_factor}:{self.walking_speed_mps}"

    def compute(self, points: list[MatrixPoint]) -> MatrixComputation:
        cells = []
        for origin in points:
            for destination in points:
                distance = haversine_meters(
                    origin.latitude, origin.longitude, destination.latitude, destination.longitude
                ) * self.detour_factor
                if origin.id == destination.id:
                    distance = 0.0
                cells.append(MatrixCell(
                    origin_id=origin.id,
                    destination_id=destination.id,
                    distance_m=distance,
                    duration_s=distance / self.walking_speed_mps,
                    reachable=True,
                ))
        return MatrixComputation(
            provider=self.name,
            profile=self.profile,
            quality=self.quality,
            cells=tuple(cells),
        )


class OSRMWalkingProvider:
    name = "osrm"
    quality = "network"

    def __init__(self, *, base_url: str, profile: str, timeout_seconds: float, block_size: int,
                 dataset_revision: str = "unverified", snap_radius_m: float = 50):
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("OSRM_BASE_URL deve usar http ou https.")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", profile):
            raise ValueError("OSRM_PROFILE contém caracteres inválidos.")
        self.base_url = base_url.rstrip("/")
        self.profile = profile
        self.timeout_seconds = timeout_seconds
        self.block_size = block_size
        self.dataset_revision = dataset_revision
        self.snap_radius_m = snap_radius_m
        if block_size <= 0 or not isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("Timeout e tamanho de bloco devem ser positivos.")
        if not isfinite(snap_radius_m) or snap_radius_m <= 0:
            raise ValueError("Raio de associação à rede deve ser positivo.")

    @property
    def cache_key(self) -> str:
        # A configuração identifica o extrato sem expor o endereço privado do serviço.
        identity = f"osrm-v2:{self.base_url}:{self.profile}:{self.dataset_revision}:{self.snap_radius_m}"
        return sha256(identity.encode()).hexdigest()

    @staticmethod
    def _number(value, *, field: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise MapProviderError(f"OSRM retornou {field} inválida.")
        number = float(value)
        if not isfinite(number) or number < 0:
            raise MapProviderError(f"OSRM retornou {field} inválida.")
        return number

    def compute(self, points: list[MatrixPoint]) -> MatrixComputation:
        cells: list[MatrixCell] = []
        versions: set[str] = set()
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                for origin_start in range(0, len(points), self.block_size):
                    origins = points[origin_start:origin_start + self.block_size]
                    for destination_start in range(0, len(points), self.block_size):
                        destinations = points[destination_start:destination_start + self.block_size]
                        combined = [*origins, *destinations]
                        coordinates = ";".join(
                            f"{point.longitude:.7f},{point.latitude:.7f}" for point in combined
                        )
                        source_indexes = ";".join(str(i) for i in range(len(origins)))
                        destination_indexes = ";".join(
                            str(i) for i in range(len(origins), len(combined))
                        )
                        url = f"{self.base_url}/table/v1/{quote(self.profile, safe='')}/{coordinates}"
                        response = client.get(url, params={
                            "sources": source_indexes,
                            "destinations": destination_indexes,
                            "annotations": "distance,duration",
                            "skip_waypoints": "true",
                            "radiuses": ";".join(str(self.snap_radius_m) for _ in combined),
                        })
                        response.raise_for_status()
                        payload = response.json()
                        if not isinstance(payload, dict):
                            raise MapProviderError("Resposta OSRM inválida.")
                        if payload.get("code") != "Ok":
                            raise MapProviderError(f"OSRM recusou a matriz: {payload.get('code', 'UNKNOWN')}.")
                        distances = payload.get("distances")
                        durations = payload.get("durations")
                        if not isinstance(distances, list) or not isinstance(durations, list):
                            raise MapProviderError("OSRM não retornou distância e duração.")
                        if len(distances) != len(origins) or len(durations) != len(origins):
                            raise MapProviderError("OSRM retornou uma matriz com dimensões inválidas.")
                        data_version = payload.get("data_version")
                        if data_version:
                            versions.add(str(data_version))
                        for i, origin in enumerate(origins):
                            if not isinstance(distances[i], list) or not isinstance(durations[i], list):
                                raise MapProviderError("Linha OSRM inválida.")
                            if len(distances[i]) != len(destinations) or len(durations[i]) != len(destinations):
                                raise MapProviderError("OSRM retornou uma linha de matriz incompleta.")
                            for j, destination in enumerate(destinations):
                                distance, duration = distances[i][j], durations[i][j]
                                if (distance is None) != (duration is None):
                                    raise MapProviderError("Custo OSRM parcialmente nulo.")
                                reachable = distance is not None and duration is not None
                                cells.append(MatrixCell(
                                    origin_id=origin.id,
                                    destination_id=destination.id,
                                    distance_m=self._number(distance, field="distância") if reachable else None,
                                    duration_s=self._number(duration, field="duração") if reachable else None,
                                    reachable=reachable,
                                    error_code=None if reachable else "NO_ROUTE",
                                ))
        except MapProviderError:
            raise
        except (httpx.HTTPError, ValueError, TypeError) as error:
            raise MapProviderError("Falha ao consultar o OSRM.") from error

        if len(cells) != len(points) ** 2:
            raise MapProviderError("OSRM retornou uma matriz incompleta.")
        if len(versions) > 1:
            raise MapProviderError("O extrato OSRM mudou entre os blocos. Repita a operação.")
        dataset_version = next(iter(versions)) if versions else self.dataset_revision
        return MatrixComputation(
            provider=self.name,
            profile=self.profile,
            quality=self.quality,
            cells=tuple(cells),
            dataset_version=dataset_version,
        )


def build_walking_provider(settings: Settings) -> WalkingMatrixProvider:
    if settings.map_provider == "straight_line":
        return StraightLineWalkingProvider(
            detour_factor=settings.straight_line_detour_factor,
            walking_speed_mps=settings.walking_speed_mps,
        )
    if settings.map_provider == "osrm":
        return OSRMWalkingProvider(
            base_url=settings.osrm_base_url,
            profile=settings.osrm_profile,
            timeout_seconds=settings.osrm_timeout_seconds,
            block_size=settings.osrm_block_size,
            dataset_revision=settings.osrm_dataset_revision,
            snap_radius_m=settings.osrm_snap_radius_m,
        )
    raise ValueError(f"MAP_PROVIDER não suportado: {settings.map_provider}.")

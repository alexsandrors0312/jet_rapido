"""Orquestra revisão geográfica, cálculo e persistência da matriz pedestre."""

from hashlib import sha256
import json
from math import isfinite

from sqlalchemy.orm import Session

from .maps import MatrixPoint, WalkingMatrixProvider
from .repository import (
    find_walking_matrix, list_delivery_points, save_walking_matrix,
)


class GeographicReviewRequired(ValueError):
    pass


class MatrixLimitExceeded(ValueError):
    pass


class InvalidMatrixResult(RuntimeError):
    pass


def _input_hash(points, provider: WalkingMatrixProvider) -> str:
    payload = {
        "provider": provider.name,
        "profile": provider.profile,
        "points": [
            {
                "id": point.id,
                "latitude": point.effective_latitude,
                "longitude": point.effective_longitude,
            }
            for point in points
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def create_walking_matrix(
    session: Session,
    *,
    route_id: str,
    provider: WalkingMatrixProvider,
    max_points: int,
    allow_unreviewed: bool,
):
    points = list_delivery_points(session, route_id)
    if not points:
        raise GeographicReviewRequired("A rota não possui pontos de entrega.")
    rejected = [point.id for point in points if point.review_status == "rejected"]
    if rejected:
        raise GeographicReviewRequired(
            f"A rota possui {len(rejected)} ponto(s) rejeitado(s); corrija-os antes da matriz."
        )
    pending = [point.id for point in points if point.review_status == "pending"]
    if pending and not allow_unreviewed:
        raise GeographicReviewRequired(
            f"A rota possui {len(pending)} ponto(s) sem revisão geográfica."
        )
    if len(points) > max_points:
        raise MatrixLimitExceeded(
            f"A rota possui {len(points)} pontos; o limite configurado é {max_points}."
        )

    input_hash = _input_hash(points, provider)
    existing = find_walking_matrix(
        session,
        route_id=route_id,
        provider=provider.name,
        profile=provider.profile,
        input_hash=input_hash,
    )
    if existing:
        return existing, True

    request_points = [
        MatrixPoint(
            id=point.id,
            latitude=point.effective_latitude,
            longitude=point.effective_longitude,
        )
        for point in points
    ]
    computation = provider.compute(request_points)
    if computation.provider != provider.name or computation.profile != provider.profile:
        raise InvalidMatrixResult("O provedor retornou uma identidade diferente da configuração.")
    expected_ids = {point.id for point in points}
    pairs = {(cell.origin_id, cell.destination_id) for cell in computation.cells}
    expected_pairs = {(origin, destination) for origin in expected_ids for destination in expected_ids}
    if pairs != expected_pairs or len(computation.cells) != len(expected_pairs):
        raise InvalidMatrixResult("O provedor retornou uma matriz incompleta ou duplicada.")
    for cell in computation.cells:
        values_present = cell.distance_m is not None and cell.duration_s is not None
        if cell.reachable != values_present:
            raise InvalidMatrixResult("O provedor retornou uma célula geográfica inconsistente.")
        if values_present and (
            not isfinite(cell.distance_m) or not isfinite(cell.duration_s)
            or cell.distance_m < 0 or cell.duration_s < 0
        ):
            raise InvalidMatrixResult("O provedor retornou custo geográfico inválido.")
        if not cell.reachable and not cell.error_code:
            raise InvalidMatrixResult("Par inacessível sem código de erro.")

    return save_walking_matrix(
        session,
        route_id=route_id,
        input_hash=input_hash,
        computation=computation,
    )

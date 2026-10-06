"""Agrupa pontos por custo pedestre dirigido, sem presumir estacionamento válido."""

from collections import defaultdict
from hashlib import sha256
import json
from math import isfinite

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .models import MacroPlan, MacroStop, MacroStopPoint, WalkingMatrix, WalkingMatrixEntry, new_uuid, utc_now
from .repository import get_route, list_delivery_points
from .walking_service import MatrixCostsInvalid, directed_matrix_costs, matrix_is_stale


ALGORITHM_VERSION = 1

# Modos de entrada da etapa 4. O padrão é estrito: pendentes só entram quando o
# operador pede explicitamente o rascunho por coordenadas efetivas.
PLANNING_MODES = ("strict", "coordinate_preview")


class MacroPlanError(ValueError):
    pass


def _coordinates_are_valid(point) -> bool:
    latitude, longitude = point.effective_latitude, point.effective_longitude
    return (
        isfinite(latitude) and isfinite(longitude)
        and -90 <= latitude <= 90 and -180 <= longitude <= 180
    )


def get_macro_plan(session: Session, plan_id: str) -> MacroPlan | None:
    return session.scalar(
        select(MacroPlan).where(MacroPlan.id == plan_id).options(
            selectinload(MacroPlan.stops).selectinload(MacroStop.assignments),
            selectinload(MacroPlan.stops).selectinload(MacroStop.candidate_base),
        )
    )


def list_macro_plans(session: Session, route_id: str, *, limit: int, offset: int) -> list[MacroPlan]:
    ids = list(session.scalars(
        select(MacroPlan.id).where(MacroPlan.route_id == route_id)
        .order_by(MacroPlan.created_at.desc(), MacroPlan.id).limit(limit).offset(offset)
    ))
    return [get_macro_plan(session, plan_id) for plan_id in ids]


def _matrix_costs(matrix: WalkingMatrix, points: list, entries: list[WalkingMatrixEntry]) -> dict:
    """Distância dirigida usada pelo agrupamento; delega a validação à etapa 5."""
    try:
        validated = directed_matrix_costs(matrix, points, entries)
    except MatrixCostsInvalid as error:
        raise MacroPlanError(str(error)) from error
    return {key: None if value is None else value[0] for key, value in validated.items()}


def _group_stats(group: tuple[str, ...], by_id: dict, costs: dict,
                 max_packages: int, max_pairwise_m: float,
                 max_base_roundtrip_m: float) -> dict | None:
    packages = sum(len(by_id[point_id].packages) for point_id in group)
    if packages > max_packages:
        return None
    pairwise = [costs[(a, b)] for a in group for b in group]
    if any(value is None or value > max_pairwise_m for value in pairwise):
        return None
    candidates = []
    for base in group:
        returns = [costs[(base, point)] + costs[(point, base)] for point in group]
        maximum = max(returns)
        if maximum <= max_base_roundtrip_m:
            candidates.append((maximum, sum(returns), by_id[base].packages[0].source_row, base))
    if not candidates:
        return None
    maximum, _, _, base = min(candidates)
    return {"points": group, "base": base, "packages": packages,
            "max_pairwise": max(pairwise), "max_roundtrip": maximum}


def _cluster(points: list, costs: dict, *, max_packages: int,
             max_pairwise_m: float, max_base_roundtrip_m: float) -> list[dict]:
    by_id = {point.id: point for point in points}
    source_order = {point.id: min(p.source_row for p in point.packages) for point in points}
    groups = [(point.id,) for point in sorted(points, key=lambda point: (source_order[point.id], point.id))]
    for group in groups:
        if _group_stats(group, by_id, costs, max_packages, max_pairwise_m, max_base_roundtrip_m) is None:
            raise MacroPlanError("Um ponto isolado excede a capacidade ou não é alcançável; revise a matriz e os pacotes.")

    # Fusão gulosa determinística. Não afirma encontrar o menor número global de bases.
    while True:
        choices = []
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                merged = tuple(sorted(groups[i] + groups[j], key=lambda pid: (source_order[pid], pid)))
                stats = _group_stats(merged, by_id, costs, max_packages, max_pairwise_m, max_base_roundtrip_m)
                if stats is not None:
                    choices.append((stats["max_roundtrip"], stats["max_pairwise"],
                                    -stats["packages"], source_order[merged[0]], merged, i, j))
        if not choices:
            break
        _, _, _, _, merged, i, j = min(choices)
        groups = [group for k, group in enumerate(groups) if k not in (i, j)] + [merged]
    groups.sort(key=lambda group: (min(source_order[pid] for pid in group), group))
    return [_group_stats(group, by_id, costs, max_packages, max_pairwise_m, max_base_roundtrip_m)
            for group in groups]


def _legacy_input_hash(input_data: dict) -> str:
    """Hash anterior à introdução de ``planning_mode``, válido só para o modo estrito.

    Propostas migradas guardam o hash calculado sem o modo. Reproduzi-lo permite
    retomar o plano estrito existente em vez de criar um duplicado. Propostas por
    coordenadas nunca usam este caminho, então o rascunho não é confundido com o
    plano estrito.
    """
    legacy = {key: value for key, value in input_data.items() if key != "planning_mode"}
    return sha256(json.dumps(legacy, sort_keys=True).encode()).hexdigest()


def create_macro_plan(session: Session, *, route_id: str, matrix_id: str,
                      provider, max_packages: int, max_pairwise_m: float,
                      max_base_roundtrip_m: float,
                      planning_mode: str = "strict") -> tuple[MacroPlan, bool]:
    if planning_mode not in PLANNING_MODES:
        raise MacroPlanError(f"Modo de planejamento desconhecido: {planning_mode}.")
    matrix = session.get(WalkingMatrix, matrix_id)
    if matrix is None or matrix.route_id != route_id:
        raise MacroPlanError("Matriz pedestre não encontrada nesta rota.")
    if matrix.quality != "network" or not matrix.input_snapshot:
        raise MacroPlanError("A etapa 4 exige matriz de rede com snapshot auditável.")
    points = list_delivery_points(session, route_id)
    if not points:
        raise MacroPlanError("A rota não possui pontos de entrega para planejar.")
    rejected = [point.id for point in points if point.review_status == "rejected"]
    if rejected:
        raise MacroPlanError(
            f"A rota possui {len(rejected)} ponto(s) rejeitado(s); corrija-os antes de planejar."
        )
    invalid = [point.id for point in points if not _coordinates_are_valid(point)]
    if invalid:
        raise MacroPlanError(
            f"A rota possui {len(invalid)} ponto(s) com coordenadas efetivas inválidas."
        )
    if planning_mode == "strict" and any(
        point.review_status not in ("confirmed", "corrected") for point in points
    ):
        raise MacroPlanError("Confirme ou corrija todos os pontos antes de planejar.")
    if matrix_is_stale(session, matrix, provider):
        raise MacroPlanError("A matriz está desatualizada. Calcule uma matriz pedestre atual.")
    input_data = {"algorithm": ALGORITHM_VERSION, "matrix_id": matrix.id,
                  "matrix_input_hash": matrix.input_hash, "max_packages": max_packages,
                  "max_pairwise_m": max_pairwise_m,
                  "max_base_roundtrip_m": max_base_roundtrip_m,
                  "planning_mode": planning_mode}
    input_hash = sha256(json.dumps(input_data, sort_keys=True).encode()).hexdigest()
    # O modo entrou no hash; propostas estritas migradas usam o hash antigo.
    legacy_hash = _legacy_input_hash(input_data) if planning_mode == "strict" else None
    existing = session.scalar(select(MacroPlan).where(
        MacroPlan.route_id == route_id, MacroPlan.input_hash == input_hash
    ))
    if existing is None and legacy_hash is not None:
        existing = session.scalar(select(MacroPlan).where(
            MacroPlan.route_id == route_id, MacroPlan.input_hash == legacy_hash,
            MacroPlan.planning_mode == "strict",
        ))
    if existing:
        return get_macro_plan(session, existing.id), True

    entries = list(session.scalars(select(WalkingMatrixEntry).where(WalkingMatrixEntry.matrix_id == matrix_id)))
    costs = _matrix_costs(matrix, points, entries)
    groups = _cluster(points, costs, max_packages=max_packages,
                      max_pairwise_m=max_pairwise_m,
                      max_base_roundtrip_m=max_base_roundtrip_m)
    assigned = [point_id for group in groups for point_id in group["points"]]
    if len(assigned) != len(set(assigned)) or set(assigned) != {point.id for point in points}:
        raise MacroPlanError("A proposta não cobre cada ponto exatamente uma vez.")
    route = get_route(session, route_id)
    if sum(group["packages"] for group in groups) != route.package_count:
        raise MacroPlanError("A proposta não cobre todos os pacotes da rota.")

    # Solta a transação de leitura para detectar revisões feitas durante o cálculo.
    session.rollback()
    matrix = session.get(WalkingMatrix, matrix_id)
    if matrix_is_stale(session, matrix, provider):
        raise MacroPlanError("A matriz mudou durante o planejamento. Gere a proposta novamente.")
    plan = MacroPlan(id=new_uuid(), route_id=route_id, walking_matrix_id=matrix_id,
                     input_hash=input_hash, planning_mode=planning_mode,
                     max_packages=max_packages,
                     max_pairwise_m=max_pairwise_m,
                     max_base_roundtrip_m=max_base_roundtrip_m)
    session.add(plan)
    for ordinal, group in enumerate(groups, start=1):
        stop = MacroStop(id=new_uuid(), plan=plan, ordinal=ordinal,
                         candidate_base_point_id=group["base"], package_count=group["packages"],
                         max_pairwise_m=group["max_pairwise"],
                         max_base_roundtrip_m=group["max_roundtrip"])
        for point_id in group["points"]:
            stop.assignments.append(MacroStopPoint(plan_id=plan.id, delivery_point_id=point_id))
        session.add(stop)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(select(MacroPlan).where(
            MacroPlan.route_id == route_id, MacroPlan.input_hash == input_hash
        ))
        if not existing:
            raise
        return get_macro_plan(session, existing.id), True
    return get_macro_plan(session, plan.id), False


def review_macro_stop(session: Session, stop_id: str, *, review_status: str,
                      review_note: str | None, provider) -> MacroStop | None:
    stop = session.get(MacroStop, stop_id)
    if stop is None:
        return None
    if matrix_is_stale(session, stop.plan.walking_matrix, provider):
        raise MacroPlanError("A proposta está desatualizada; gere outra antes da revisão.")
    stop.review_status = review_status
    stop.review_note = review_note
    stop.reviewed_at = utc_now()
    session.commit()
    return stop


def _review_counts(plan: MacroPlan, points: dict) -> tuple[int, int, str]:
    """Conta as revisões da entrada imutável que originou a proposta.

    O snapshot ``input_snapshot['points']`` registra ``review_status`` no momento
    em que a matriz foi calculada. É essa a entrada da proposta: usar o estado
    atual faria a proposta stale exibir contagens diferentes das que a criaram.
    Propostas legadas sem snapshot caem no estado atual com sinalização
    explícita e continuam ``stale`` por ``matrix_is_stale``.
    """
    matrix = plan.walking_matrix
    snapshot = matrix.input_snapshot if matrix is not None else None
    snapshot_points = snapshot.get("points") if isinstance(snapshot, dict) else None
    if snapshot_points and all(
        isinstance(entry, dict) and "review_status" in entry for entry in snapshot_points
    ):
        pending = sum(1 for entry in snapshot_points if entry["review_status"] == "pending")
        reviewed = sum(1 for entry in snapshot_points
                       if entry["review_status"] in ("confirmed", "corrected"))
        return pending, reviewed, "plan_input_snapshot"
    pending = sum(1 for point in points.values() if point.review_status == "pending")
    reviewed = sum(1 for point in points.values() if point.review_status in ("confirmed", "corrected"))
    return pending, reviewed, "legacy_current_points"


def macro_plan_response(session: Session, plan: MacroPlan, provider, *, idempotent=False) -> dict:
    route = get_route(session, plan.route_id)
    points = {point.id: point for point in list_delivery_points(session, plan.route_id)}
    original_to_groups = defaultdict(set)
    stops = []
    multi_address_count = 0
    packages_in_multi_address = 0
    cross_street_count = 0
    for stop in plan.stops:
        assigned = sorted((points[a.delivery_point_id] for a in stop.assignments),
                          key=lambda point: (min(p.source_row for p in point.packages), point.id))
        packages = [package for point in assigned for package in point.packages]
        street_count = len({package.street_key for package in packages})
        if len(assigned) > 1:
            multi_address_count += 1
            packages_in_multi_address += len(packages)
            if street_count > 1:
                cross_street_count += 1
        for package in packages:
            if package.original_stop is not None:
                original_to_groups[package.original_stop].add(stop.id)
        stops.append({"id": stop.id, "ordinal": stop.ordinal,
                      "candidate_base_point_id": stop.candidate_base_point_id,
                      "candidate_base_address": stop.candidate_base.original_address,
                      "parking_status": "unverified", "delivery_point_ids": [point.id for point in assigned],
                      "delivery_point_count": len(assigned), "street_count": street_count,
                      "stop_type": "multi_address_walk_candidate" if len(assigned) > 1 else "single_address_stop",
                      "package_count": stop.package_count,
                      "original_stops": sorted({p.original_stop for p in packages if p.original_stop is not None}),
                      "max_pairwise_m": stop.max_pairwise_m,
                      "max_base_roundtrip_m": stop.max_base_roundtrip_m,
                      "review_status": stop.review_status, "review_note": stop.review_note,
                      "reviewed_at": stop.reviewed_at})
    covered = [a.delivery_point_id for stop in plan.stops for a in stop.assignments]
    pending, reviewed, review_counts_basis = _review_counts(plan, points)
    provisional = plan.planning_mode == "coordinate_preview"
    if provisional:
        review_notice = (
            f"Rascunho não homologado: {pending} entrada(s) pendente(s) na entrada "
            "da proposta foram agrupadas pelas coordenadas efetivas. Nenhum status "
            "de revisão foi alterado; portões, travessias, estacionamento e "
            "capacidade da bag seguem sem validação física."
        )
    else:
        review_notice = (
            "Proposta no modo estrito: as entradas da proposta estavam confirmadas "
            "ou corrigidas. Portões, travessias, estacionamento e capacidade da bag "
            "seguem sem validação física."
        )
    if review_counts_basis == "legacy_current_points":
        review_notice += (
            " Sem snapshot de entrada: as contagens usam o estado atual dos pontos "
            "e a proposta permanece desatualizada."
        )
    return {"id": plan.id, "route_id": plan.route_id, "walking_matrix_id": plan.walking_matrix_id,
            "input_hash": plan.input_hash, "created_at": plan.created_at,
            "stale": matrix_is_stale(session, plan.walking_matrix, provider),
            "idempotent": idempotent, "planning_mode": plan.planning_mode,
            "provisional_draft": provisional, "pending_point_count": pending,
            "reviewed_point_count": reviewed, "review_counts_basis": review_counts_basis,
            "review_notice": review_notice,
            "max_packages": plan.max_packages,
            "max_pairwise_m": plan.max_pairwise_m,
            "max_base_roundtrip_m": plan.max_base_roundtrip_m,
            "package_count": sum(stop.package_count for stop in plan.stops),
            "point_count": len(covered), "exact_coverage": len(covered) == len(set(covered)) == len(points)
                              and set(covered) == set(points),
            "original_stop_count": route.original_stop_count,
            "packages_without_original_stop": sum(p.original_stop is None for p in route.packages),
            "original_stops_split": sum(len(groups) > 1 for groups in original_to_groups.values()),
            "macro_stop_count": len(stops),
            "multi_address_stop_count": multi_address_count,
            "single_address_stop_count": len(stops) - multi_address_count,
            "cross_street_stop_count": cross_street_count,
            "packages_in_multi_address_stops": packages_in_multi_address,
            "distance_comparison_available": False,
            "distance_comparison_note": "A planilha não informa estacionamento original nem percurso a pé; não é possível medir economia de caminhada ou retornos.",
            "stops": stops}

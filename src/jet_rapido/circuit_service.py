"""Circuitos pedestres fechados e dirigidos para macro-paradas (rascunho da etapa 5).

O cálculo é determinístico e sob demanda: usa somente a matriz pedestre ``foot``
persistida de uma proposta existente, sem gerar geometria, instruções de manobra
ou voz e sem prometer economia operacional. A base é a entrada candidata da
macro-parada, não um estacionamento validado.
"""

from hashlib import sha256
from itertools import permutations
import json
from math import isfinite

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import WalkingMatrixEntry
from .repository import list_delivery_points
from .walking_service import MatrixCostsInvalid, directed_matrix_costs, matrix_is_stale


ALGORITHM_VERSION = 1

# Grupos maiores que este limite de pontos deixam de ter solução exata
# enumerável e passam por heurística determinística marcada como não ótima.
EXACT_POINT_LIMIT = 9

ORDER_RULE = "directed_distance_then_duration_then_canonical"
DISTANCE_BASIS = "walking_matrix_entries"

BASE_NOTICE = (
    "A base é uma coordenada de endereço candidata, não um estacionamento "
    "validado. Vagas, acessos e permissões seguem sem confirmação."
)
GPS_NOTICE = (
    "A partida real deve usar o GPS confirmado do veículo para calcular a rota "
    "final. O circuito aqui é uma sequência de pontos sobre a matriz de custos, "
    "não uma rota navegável."
)
CAPABILITY_NOTICE = (
    "Sem geometria, instruções de manobra ou voz: a matriz de custos otimiza "
    "distância e duração entre pontos e não descreve o traçado. Nenhuma economia "
    "operacional é prometida."
)
HEURISTIC_NOTICE = (
    f"Grupos acima de {EXACT_POINT_LIMIT} pontos usam heurística determinística "
    "(vizinho mais próximo com 2-opt) marcada como não ótima."
)
HEURISTIC_NOT_FOUND_NOTICE = (
    "O método heurístico não encontrou um circuito fechado para o grupo com as "
    "pernas disponíveis; a existência de caminho não foi descartada. Revise a "
    "matriz ou reduza o grupo."
)
BASE_ROUNDTRIP_LIMIT_NOTICE = (
    "O parâmetro max_base_roundtrip_m limita cada ida e volta individual entre a "
    "base candidata e um endereço do grupo; ele não limita a distância total do "
    "circuito fechado que visita vários pontos. Um circuito acima do parâmetro "
    "não bloqueia nem altera o agrupamento da etapa 4 automaticamente."
)


def _roundtrip_warning(ordinal: int, distance: float, limit: float) -> str | None:
    """Aviso por circuito quando a volta completa supera o parâmetro da etapa 4."""
    if distance <= limit:
        return None
    return (
        f"A macro-parada {ordinal} tem distância total de circuito {distance:.1f} m, "
        f"acima do parâmetro max_base_roundtrip_m de {limit:.1f} m. Esse parâmetro "
        "limita cada ida e volta individual à base, não a volta completa que visita "
        "vários pontos; o agrupamento não é bloqueado nem alterado automaticamente."
    )


class CircuitError(ValueError):
    pass


def _load_directed_costs(session: Session, matrix, points: list) -> dict:
    entries = list(session.scalars(
        select(WalkingMatrixEntry).where(WalkingMatrixEntry.matrix_id == matrix.id)
    ))
    try:
        return directed_matrix_costs(matrix, points, entries)
    except MatrixCostsInvalid as error:
        raise CircuitError(str(error)) from error


def _sequence_cost(sequence: tuple[str, ...], costs: dict) -> tuple[float, float] | None:
    """Custo dirigido do circuito fechado; ``None`` se alguma perna for inacessível."""
    distance = 0.0
    duration = 0.0
    length = len(sequence)
    for index in range(length):
        origin = sequence[index]
        destination = sequence[(index + 1) % length]
        value = costs.get((origin, destination))
        if value is None:
            return None
        distance += value[0]
        duration += value[1]
    return distance, duration


def _solve_exact(base: str, others: list[str], costs: dict,
                 ranks: dict) -> tuple[tuple[str, ...], float, float]:
    best = None
    best_key = None
    for permutation in permutations(others):
        sequence = (base,) + permutation
        result = _sequence_cost(sequence, costs)
        if result is None:
            continue
        key = (result[0], result[1], tuple(ranks[point_id] for point_id in sequence))
        if best_key is None or key < best_key:
            best_key = key
            best = (sequence, result[0], result[1])
    if best is None:
        raise CircuitError(
            "Nenhum circuito fechado é viável para o grupo sem atravessar par inacessível."
        )
    return best


def _two_opt(sequence: list[str], costs: dict) -> list[str]:
    length = len(sequence)
    if length < 3:
        return list(sequence)
    while True:
        best_cost = _sequence_cost(tuple(sequence), costs)
        best_choice = None
        best_key = None
        for start in range(1, length - 1):
            for end in range(start + 1, length):
                candidate = sequence[:start] + list(reversed(sequence[start:end + 1])) + sequence[end + 1:]
                result = _sequence_cost(tuple(candidate), costs)
                if result is None:
                    continue
                key = (result[0], result[1], start, end)
                if best_key is None or key < best_key:
                    best_key = key
                    best_choice = candidate
        if best_choice is None:
            return sequence
        if best_cost is not None and best_key[:2] >= best_cost:
            return sequence
        sequence = best_choice


def _solve_heuristic(base: str, others: list[str], costs: dict,
                     ranks: dict) -> tuple[tuple[str, ...], float, float]:
    remaining = set(others)
    sequence = [base]
    current = base
    while remaining:
        candidates = []
        for point_id in remaining:
            value = costs.get((current, point_id))
            if value is not None:
                candidates.append((value[0], value[1], ranks[point_id], point_id))
        if not candidates:
            raise CircuitError(HEURISTIC_NOT_FOUND_NOTICE)
        *_, next_point = min(candidates)
        sequence.append(next_point)
        remaining.discard(next_point)
        current = next_point
    improved = _two_opt(sequence, costs)
    result = _sequence_cost(tuple(improved), costs)
    if result is None:
        raise CircuitError(HEURISTIC_NOT_FOUND_NOTICE)
    return tuple(improved), result[0], result[1]


def _legs(sequence: tuple[str, ...], costs: dict, stop_ordinal: int) -> tuple[list[dict], float, float]:
    legs = []
    distance = 0.0
    duration = 0.0
    length = len(sequence)
    for index in range(length):
        origin = sequence[index]
        destination = sequence[(index + 1) % length]
        value = costs.get((origin, destination))
        if value is None:
            raise CircuitError(
                f"A macro-parada {stop_ordinal} exige um par inacessível; revise a matriz."
            )
        if not isfinite(value[0]) or not isfinite(value[1]):
            raise CircuitError(f"A macro-parada {stop_ordinal} possui custo geográfico inválido.")
        distance += value[0]
        duration += value[1]
        legs.append({
            "origin_delivery_point_id": origin,
            "destination_delivery_point_id": destination,
            "distance_m": value[0],
            "duration_s": value[1],
        })
    return legs, distance, duration


def _solve_stop(stop, group_ids: list[str], costs: dict, ranks: dict,
                base_roundtrip_limit: float) -> dict:
    base = stop.candidate_base_point_id
    ordered_group = sorted(group_ids, key=lambda point_id: ranks[point_id])
    others = [point_id for point_id in ordered_group if point_id != base]
    if len(ordered_group) <= EXACT_POINT_LIMIT:
        sequence, distance, duration = _solve_exact(base, others, costs, ranks)
        method, optimal = "exact", True
    else:
        sequence, distance, duration = _solve_heuristic(base, others, costs, ranks)
        method, optimal = "heuristic_nearest_neighbor_2opt", False
    legs, distance, duration = _legs(sequence, costs, stop.ordinal)
    warning = _roundtrip_warning(stop.ordinal, distance, base_roundtrip_limit)
    return {
        "stop_id": stop.id,
        "ordinal": stop.ordinal,
        "candidate_base_point_id": base,
        "base_status": "unverified",
        "delivery_point_ids": ordered_group,
        "sequence_point_ids": list(sequence),
        "closed": True,
        "point_count": len(sequence),
        "package_count": stop.package_count,
        "distance_m": distance,
        "duration_s": duration,
        "solution_method": method,
        "optimal": optimal,
        "max_base_roundtrip_m": base_roundtrip_limit,
        "exceeds_base_roundtrip_limit": warning is not None,
        "roundtrip_warning": warning,
        "legs": legs,
    }


def _draft_notice(plan) -> str:
    if plan.planning_mode == "coordinate_preview":
        return (
            "Rascunho por coordenadas não homologado: os circuitos usam a base "
            "candidata da proposta e não alteram nenhum status de revisão."
        )
    return (
        "Proposta estrita: os circuitos usam a base candidata e não alteram "
        "nenhum status de revisão."
    )


def _content_hash(circuits: list[dict]) -> str:
    canonical = [
        {
            "stop_id": circuit["stop_id"],
            "sequence": circuit["sequence_point_ids"],
            "distance_m": circuit["distance_m"],
            "duration_s": circuit["duration_s"],
            "method": circuit["solution_method"],
        }
        for circuit in circuits
    ]
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def build_macro_plan_circuits(session: Session, plan, provider) -> dict:
    """Circuito fechado e dirigido de cada macro-parada de uma proposta existente."""
    matrix = plan.walking_matrix
    if matrix is None or matrix.route_id != plan.route_id:
        raise CircuitError("A proposta não aponta para uma matriz pedestre da mesma rota.")
    points = list_delivery_points(session, plan.route_id)
    if not points:
        raise CircuitError("A rota não possui pontos de entrega para o circuito.")
    by_id = {point.id: point for point in points}
    order_key = {
        point.id: (min(package.source_row for package in point.packages), point.id)
        for point in points
    }
    # Ordem canônica por planilha e identificador; nenhum endereço textual entra na ordenação.
    ranks = {
        point_id: index
        for index, point_id in enumerate(sorted(by_id, key=lambda pid: order_key[pid]))
    }

    if matrix.quality != "network":
        raise CircuitError(
            "O circuito exige matriz de rede; a estimativa em linha reta é recusada."
        )
    if not matrix.input_snapshot:
        raise CircuitError("O circuito exige uma matriz com snapshot auditável.")
    if matrix_is_stale(session, matrix, provider):
        raise CircuitError("A proposta está desatualizada; gere outra antes de calcular os circuitos.")
    costs = _load_directed_costs(session, matrix, points)

    assigned: list[str] = []
    circuits = []
    base_roundtrip_limit = plan.max_base_roundtrip_m
    for stop in plan.stops:
        group_ids = [assignment.delivery_point_id for assignment in stop.assignments]
        if not group_ids:
            raise CircuitError(f"A macro-parada {stop.ordinal} não possui pontos de entrega.")
        if any(point_id not in by_id for point_id in group_ids):
            raise CircuitError("Uma macro-parada referencia ponto de outra rota.")
        if stop.candidate_base_point_id not in group_ids:
            raise CircuitError(f"A base da macro-parada {stop.ordinal} não pertence ao grupo.")
        circuits.append(_solve_stop(stop, group_ids, costs, ranks, base_roundtrip_limit))
        assigned.extend(group_ids)

    if len(assigned) != len(set(assigned)) or set(assigned) != set(by_id):
        raise CircuitError("Os circuitos não cobrem cada ponto exatamente uma vez.")

    total_distance = sum(circuit["distance_m"] for circuit in circuits)
    total_duration = sum(circuit["duration_s"] for circuit in circuits)
    exact_count = sum(1 for circuit in circuits if circuit["optimal"])
    heuristic_count = len(circuits) - exact_count
    exceeding_count = sum(1 for circuit in circuits if circuit["exceeds_base_roundtrip_limit"])
    provisional = plan.planning_mode == "coordinate_preview"
    return {
        "plan_id": plan.id,
        "route_id": plan.route_id,
        "walking_matrix_id": matrix.id,
        "matrix_quality": matrix.quality,
        "planning_mode": plan.planning_mode,
        "provisional_draft": provisional,
        "stale": False,
        "algorithm_version": ALGORITHM_VERSION,
        "order_rule": ORDER_RULE,
        "distance_basis": DISTANCE_BASIS,
        "exact_point_limit": EXACT_POINT_LIMIT,
        "max_base_roundtrip_m": base_roundtrip_limit,
        "base_status": "unverified",
        "base_notice": BASE_NOTICE,
        "base_roundtrip_limit_notice": BASE_ROUNDTRIP_LIMIT_NOTICE,
        "gps_notice": GPS_NOTICE,
        "capability_notice": CAPABILITY_NOTICE,
        "heuristic_notice": HEURISTIC_NOTICE,
        "draft_notice": _draft_notice(plan),
        "geometry_available": False,
        "maneuvers_available": False,
        "voice_available": False,
        "circuit_count": len(circuits),
        "exact_circuit_count": exact_count,
        "heuristic_circuit_count": heuristic_count,
        "all_circuits_exact": heuristic_count == 0,
        "circuits_exceeding_base_roundtrip": exceeding_count,
        "exact_coverage": True,
        "point_count": len(assigned),
        "package_count": sum(stop.package_count for stop in plan.stops),
        "total_distance_m": total_distance,
        "total_duration_s": total_duration,
        "content_hash": _content_hash(circuits),
        "circuits": circuits,
    }

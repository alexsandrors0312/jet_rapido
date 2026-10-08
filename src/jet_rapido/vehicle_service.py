"""Ordem veicular aberta entre macro-paradas (etapa 5).

Calcula, para uma proposta de macro-paradas existente, a sequência
``partida -> cada base candidata exatamente uma vez -> chegada`` sobre uma
**matriz dirigida de rede veicular** persistida. O custo vem apenas de uma matriz
OSRM de perfil veicular (``car``): nem a matriz pedestre nem a estimativa em
linha reta substituem a via. Rótulos e endereços não entram no objetivo.

É um rascunho: a base é uma coordenada de entrega candidata, não um
estacionamento validado; não há geometria, manobras, voz nem economia
operacional.
"""

from dataclasses import dataclass
from hashlib import sha256
from math import isfinite
import json

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .maps import MatrixPoint, is_pedestrian_profile
from .models import VehicleMatrix, VehicleMatrixEntry, new_uuid
from .repository import list_delivery_points
from .walking_service import matrix_is_stale


ALGORITHM_VERSION = 1

# Endpoints são nós sintéticos; as bases e demais entregas usam um prefixo.
ORIGIN_NODE_ID = "origin"
DESTINATION_NODE_ID = "destination"
DELIVERY_NODE_PREFIX = "delivery:"

# Limite de bases com solução exata por programação dinâmica (Held-Karp). Para as
# propostas reais atuais (8 e 11 bases) o resultado é ótimo.
EXACT_BASE_LIMIT = 12

ORDER_RULE = "directed_distance_then_duration_then_canonical"
DISTANCE_BASIS = "vehicle_matrix_entries"

PARKING_NOTICE = (
    "A base é a coordenada de entrega candidata da macro-parada, não uma vaga "
    "validada. Estacionamento, acesso de veículo e permissão seguem sem confirmação."
)
GPS_NOTICE = (
    "A partida real deve usar o GPS confirmado do veículo. A ordem aqui é uma "
    "sequência de bases sobre a matriz de custos, não uma rota navegável."
)
CAPABILITY_NOTICE = (
    "Sem geometria, instruções de manobra ou voz: a matriz otimiza distância e "
    "duração entre bases e não descreve o traçado. Nenhuma economia operacional "
    "é prometida."
)
HEURISTIC_NOTICE = (
    f"Acima de {EXACT_BASE_LIMIT} bases a ordem usa heurística determinística "
    "(vizinho mais próximo com 2-opt) marcada como não ótima."
)
HEURISTIC_NOT_FOUND_NOTICE = (
    "O método heurístico não encontrou uma ordem viável para as bases com as "
    "pernas disponíveis; a existência de caminho não foi descartada. Revise a "
    "matriz veicular ou reduza o número de macro-paradas."
)
EXACT_NOT_FOUND_NOTICE = (
    "Nenhuma ordem viável visita cada base uma vez sem atravessar par "
    "inacessível. Corrija a matriz veicular ou o número de macro-paradas."
)
MATRIX_MISSING_NOTICE = (
    "Nenhum provedor veicular de rede está configurado. A ordem veicular exige um "
    "conjunto de dados OSRM de perfil car com endpoint, revisão e perfil próprios; "
    "a matriz pedestre e a estimativa em linha reta não substituem a via."
)


@dataclass(frozen=True)
class VehicleEndpoint:
    latitude: float
    longitude: float
    label: str | None = None


class VehicleOrderError(ValueError):
    """Recusa clara da ordem veicular; nenhuma conectividade é presumida."""


def delivery_node_id(point_id: str) -> str:
    return f"{DELIVERY_NODE_PREFIX}{point_id}"


def node_role(node_id: str) -> str:
    if node_id == ORIGIN_NODE_ID:
        return "origin"
    if node_id == DESTINATION_NODE_ID:
        return "destination"
    return "candidate_base"


def endpoint_from_snapshot(snapshot: dict, key: str) -> VehicleEndpoint:
    entry = snapshot[key]
    return VehicleEndpoint(
        latitude=float(entry["latitude"]),
        longitude=float(entry["longitude"]),
        label=entry.get("label"),
    )


def validate_endpoint(endpoint: VehicleEndpoint, role: str) -> VehicleEndpoint:
    latitude, longitude = endpoint.latitude, endpoint.longitude
    if not isfinite(latitude) or not isfinite(longitude):
        raise VehicleOrderError(f"A coordenada de {role} precisa ser numérica.")
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise VehicleOrderError(f"A coordenada de {role} está fora dos limites geográficos.")
    label = endpoint.label
    if label is not None:
        label = label.strip() or None
    return VehicleEndpoint(latitude=latitude, longitude=longitude, label=label)


def _provider_identity(provider) -> dict:
    return {
        "provider": provider.name,
        "profile": provider.profile,
        "quality": provider.quality,
        "dataset_revision": getattr(provider, "dataset_revision", None),
        "provider_key": getattr(provider, "cache_key", f"{provider.name}:{provider.profile}"),
    }


def _snapshot(points: list, origin: VehicleEndpoint, destination: VehicleEndpoint,
              provider) -> dict:
    snapshot = _provider_identity(provider)
    snapshot.update({
        "origin": {
            "node_id": ORIGIN_NODE_ID, "latitude": origin.latitude,
            "longitude": origin.longitude, "label": origin.label,
        },
        "destination": {
            "node_id": DESTINATION_NODE_ID, "latitude": destination.latitude,
            "longitude": destination.longitude, "label": destination.label,
        },
        "points": [
            {
                "node_id": delivery_node_id(point.id),
                "delivery_point_id": point.id,
                "latitude": point.effective_latitude,
                "longitude": point.effective_longitude,
                "revision": point.revision,
                "review_status": point.review_status,
            }
            for point in sorted(points, key=lambda point: point.id)
        ],
    })
    return snapshot


def _identity(snapshot: dict) -> dict:
    """Identidade do custo: sem rótulos, que são apenas apresentação."""
    identity = {
        key: snapshot[key]
        for key in ("provider", "profile", "quality", "dataset_revision", "provider_key")
    }
    identity["origin"] = {
        "latitude": snapshot["origin"]["latitude"],
        "longitude": snapshot["origin"]["longitude"],
    }
    identity["destination"] = {
        "latitude": snapshot["destination"]["latitude"],
        "longitude": snapshot["destination"]["longitude"],
    }
    identity["points"] = snapshot["points"]
    return identity


def _hash(identity: dict) -> str:
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def vehicle_matrix_is_stale(session: Session, matrix: VehicleMatrix, provider) -> bool:
    snapshot = matrix.input_snapshot
    if not isinstance(snapshot, dict) or "origin" not in snapshot or "destination" not in snapshot:
        return True
    if provider is None:
        return True
    origin = endpoint_from_snapshot(snapshot, "origin")
    destination = endpoint_from_snapshot(snapshot, "destination")
    points = list_delivery_points(session, matrix.route_id)
    expected = _hash(_identity(_snapshot(points, origin, destination, provider)))
    return matrix.input_hash != expected


def _ensure_provider(provider, *, max_points: int, node_count: int) -> None:
    if provider is None:
        raise VehicleOrderError(MATRIX_MISSING_NOTICE)
    if is_pedestrian_profile(getattr(provider, "profile", "")):
        raise VehicleOrderError(
            "O perfil do provedor veicular é pedestre. A ordem veicular exige um "
            "conjunto de dados car; chamar um extrato pedestre com /driving não muda o custo."
        )
    if getattr(provider, "quality", None) != "network":
        raise VehicleOrderError(
            "A ordem veicular exige provedor de rede. A estimativa em linha reta não "
            "representa acessos, barreiras ou mão de direção."
        )
    if node_count > max_points:
        raise VehicleOrderError(
            f"A matriz veicular teria {node_count} nós; o limite configurado é {max_points}."
        )


def _validate_computation(provider, computation, expected_ids: set[str]) -> None:
    if (computation.provider, computation.profile, computation.quality) != (
        provider.name, provider.profile, provider.quality
    ):
        raise VehicleOrderError("O provedor veicular retornou uma identidade diferente da configuração.")
    pairs = {(cell.origin_id, cell.destination_id) for cell in computation.cells}
    expected_pairs = {(origin, destination) for origin in expected_ids for destination in expected_ids}
    if pairs != expected_pairs or len(computation.cells) != len(expected_pairs):
        raise VehicleOrderError("O provedor veicular retornou uma matriz incompleta ou duplicada.")
    for cell in computation.cells:
        values_present = cell.distance_m is not None and cell.duration_s is not None
        if cell.reachable != values_present:
            raise VehicleOrderError("O provedor veicular retornou uma célula inconsistente.")
        if values_present and (
            not isfinite(cell.distance_m) or not isfinite(cell.duration_s)
            or cell.distance_m < 0 or cell.duration_s < 0
        ):
            raise VehicleOrderError("O provedor veicular retornou custo inválido.")
        if not cell.reachable and (not cell.error_code or values_present):
            raise VehicleOrderError("Par inacessível inconsistente na matriz veicular.")


def create_vehicle_matrix(
    session: Session,
    *,
    route_id: str,
    origin: VehicleEndpoint,
    destination: VehicleEndpoint,
    provider,
    max_points: int,
) -> tuple[VehicleMatrix, bool]:
    points = list_delivery_points(session, route_id)
    if not points:
        raise VehicleOrderError("A rota não possui pontos de entrega para a ordem veicular.")
    invalid = [
        point.id for point in points
        if not (isfinite(point.effective_latitude) and isfinite(point.effective_longitude)
                and -90 <= point.effective_latitude <= 90
                and -180 <= point.effective_longitude <= 180)
    ]
    if invalid:
        raise VehicleOrderError(
            f"A rota possui {len(invalid)} ponto(s) com coordenadas efetivas inválidas."
        )
    _ensure_provider(provider, max_points=max_points, node_count=len(points) + 2)

    origin = validate_endpoint(origin, "partida")
    destination = validate_endpoint(destination, "chegada")
    snapshot = _snapshot(points, origin, destination, provider)
    input_hash = _hash(_identity(snapshot))
    existing = session.scalar(select(VehicleMatrix).where(
        VehicleMatrix.route_id == route_id,
        VehicleMatrix.provider == provider.name,
        VehicleMatrix.profile == provider.profile,
        VehicleMatrix.input_hash == input_hash,
    ))
    if existing:
        return existing, True

    request_points = [
        MatrixPoint(ORIGIN_NODE_ID, origin.latitude, origin.longitude),
        MatrixPoint(DESTINATION_NODE_ID, destination.latitude, destination.longitude),
        *[
            MatrixPoint(delivery_node_id(point.id), point.effective_latitude, point.effective_longitude)
            for point in points
        ],
    ]
    expected_ids = {point.id for point in request_points}
    computation = provider.compute(request_points)
    _validate_computation(provider, computation, expected_ids)

    # Encerra a leitura anterior para detectar revisões feitas durante a consulta.
    session.rollback()
    current = list_delivery_points(session, route_id)
    if _hash(_identity(_snapshot(current, origin, destination, provider))) != input_hash:
        raise VehicleOrderError("Os pontos ou a rede mudaram durante o cálculo. Repita a operação.")

    reachable_pairs = sum(cell.reachable for cell in computation.cells)
    matrix = VehicleMatrix(
        id=new_uuid(),
        route_id=route_id,
        provider=computation.provider,
        profile=computation.profile,
        quality=computation.quality,
        dataset_revision=getattr(provider, "dataset_revision", None),
        input_hash=input_hash,
        input_snapshot=snapshot,
        point_count=len(expected_ids),
        reachable_pairs=reachable_pairs,
        unreachable_pairs=len(computation.cells) - reachable_pairs,
    )
    session.add(matrix)
    for cell in computation.cells:
        session.add(VehicleMatrixEntry(
            matrix=matrix,
            origin_node_id=cell.origin_id,
            destination_node_id=cell.destination_id,
            distance_m=cell.distance_m,
            duration_s=cell.duration_s,
            reachable=cell.reachable,
            error_code=cell.error_code,
        ))
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(select(VehicleMatrix).where(
            VehicleMatrix.route_id == route_id,
            VehicleMatrix.provider == provider.name,
            VehicleMatrix.profile == provider.profile,
            VehicleMatrix.input_hash == input_hash,
        ))
        if existing:
            return existing, True
        raise
    return matrix, False


def _load_costs(session: Session, matrix: VehicleMatrix, node_ids: set[str]) -> dict:
    entries = list(session.scalars(
        select(VehicleMatrixEntry).where(VehicleMatrixEntry.matrix_id == matrix.id)
    ))
    if matrix.point_count != len(node_ids) or len(entries) != len(node_ids) ** 2:
        raise VehicleOrderError("A matriz veicular não cobre todos os pares dos nós exigidos.")
    costs: dict[tuple[str, str], tuple[float, float] | None] = {}
    for entry in entries:
        key = (entry.origin_node_id, entry.destination_node_id)
        if key in costs or key[0] not in node_ids or key[1] not in node_ids:
            raise VehicleOrderError("A matriz veicular contém pares duplicados ou nós de outra rota.")
        if entry.reachable:
            if (entry.distance_m is None or entry.duration_s is None
                    or not isfinite(entry.distance_m) or not isfinite(entry.duration_s)
                    or entry.distance_m < 0 or entry.duration_s < 0):
                raise VehicleOrderError("A matriz veicular contém custos inválidos.")
            costs[key] = (entry.distance_m, entry.duration_s)
        else:
            if entry.distance_m is not None or entry.duration_s is not None or not entry.error_code:
                raise VehicleOrderError("A matriz veicular contém um par inacessível inconsistente.")
            costs[key] = None
    if len(costs) != len(node_ids) ** 2:
        raise VehicleOrderError("A matriz veicular está incompleta.")
    return costs


def _path_cost(sequence: tuple[str, ...], costs: dict) -> tuple[float, float] | None:
    distance = 0.0
    duration = 0.0
    for index in range(len(sequence) - 1):
        value = costs.get((sequence[index], sequence[index + 1]))
        if value is None:
            return None
        distance += value[0]
        duration += value[1]
    return distance, duration


def _solve_exact(origin: str, bases: list[str], destination: str, costs: dict,
                 ranks: dict) -> tuple[tuple[str, ...], float, float]:
    """Caminho aberto ótimo por programação dinâmica (Held-Karp).

    A chave de cada estado é ``(distância, duração, sequência de ranks)``, então o
    desempate é por duração da mesma sequência e depois pela ordem canônica.
    """
    count = len(bases)
    if count == 0:
        result = _path_cost((origin, destination), costs)
        if result is None:
            raise VehicleOrderError(EXACT_NOT_FOUND_NOTICE)
        return (origin, destination), result[0], result[1]
    full = (1 << count) - 1
    states: dict[tuple[int, int], tuple[float, float, tuple[int, ...]]] = {}
    for index in range(count):
        value = costs.get((origin, bases[index]))
        if value is None:
            continue
        states[(1 << index, index)] = (value[0], value[1], (ranks[bases[index]],))
    for mask in range(1, full + 1):
        for index in range(count):
            if not (mask >> index) & 1:
                continue
            state = states.get((mask, index))
            if state is None:
                continue
            for following in range(count):
                if (mask >> following) & 1:
                    continue
                value = costs.get((bases[index], bases[following]))
                if value is None:
                    continue
                candidate = (
                    state[0] + value[0],
                    state[1] + value[1],
                    state[2] + (ranks[bases[following]],),
                )
                key = (mask | (1 << following), following)
                current = states.get(key)
                if current is None or candidate < current:
                    states[key] = candidate
    best = None
    for index in range(count):
        state = states.get((full, index))
        if state is None:
            continue
        value = costs.get((bases[index], destination))
        if value is None:
            continue
        candidate = (state[0] + value[0], state[1] + value[1], state[2])
        if best is None or candidate < best:
            best = candidate
    if best is None:
        raise VehicleOrderError(EXACT_NOT_FOUND_NOTICE)
    by_rank = {ranks[base]: base for base in bases}
    sequence = (origin,) + tuple(by_rank[rank] for rank in best[2]) + (destination,)
    return sequence, best[0], best[1]


def _two_opt(sequence: list[str], costs: dict) -> list[str]:
    length = len(sequence)
    if length < 4:
        return list(sequence)
    while True:
        best_cost = _path_cost(tuple(sequence), costs)
        best_choice = None
        best_key = None
        for start in range(1, length - 2):
            for end in range(start + 1, length - 1):
                candidate = sequence[:start] + list(reversed(sequence[start:end + 1])) + sequence[end + 1:]
                result = _path_cost(tuple(candidate), costs)
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


def _solve_heuristic(origin: str, bases: list[str], destination: str, costs: dict,
                     ranks: dict) -> tuple[tuple[str, ...], float, float]:
    remaining = set(bases)
    sequence = [origin]
    current = origin
    while remaining:
        candidates = []
        for base in remaining:
            value = costs.get((current, base))
            if value is not None:
                candidates.append((value[0], value[1], ranks[base], base))
        if not candidates:
            raise VehicleOrderError(HEURISTIC_NOT_FOUND_NOTICE)
        *_, following = min(candidates)
        sequence.append(following)
        remaining.discard(following)
        current = following
    if costs.get((current, destination)) is None:
        raise VehicleOrderError(HEURISTIC_NOT_FOUND_NOTICE)
    sequence.append(destination)
    improved = _two_opt(sequence, costs)
    result = _path_cost(tuple(improved), costs)
    if result is None:
        raise VehicleOrderError(HEURISTIC_NOT_FOUND_NOTICE)
    return tuple(improved), result[0], result[1]


def _legs(sequence: tuple[str, ...], costs: dict) -> tuple[list[dict], float, float]:
    legs = []
    distance = 0.0
    duration = 0.0
    for index in range(len(sequence) - 1):
        origin, destination = sequence[index], sequence[index + 1]
        value = costs.get((origin, destination))
        if value is None:
            raise VehicleOrderError(
                "A ordem escolhida exige um par inacessível; revise a matriz veicular."
            )
        if not isfinite(value[0]) or not isfinite(value[1]):
            raise VehicleOrderError("A ordem escolhida possui custo geográfico inválido.")
        distance += value[0]
        duration += value[1]
        legs.append({
            "position": index + 1,
            "origin_node_id": origin,
            "destination_node_id": destination,
            "origin_role": node_role(origin),
            "destination_role": node_role(destination),
            "distance_m": value[0],
            "duration_s": value[1],
        })
    return legs, distance, duration


def _content_hash(sequence: tuple[str, ...], legs: list[dict], method: str) -> str:
    canonical = {
        "sequence": list(sequence),
        "method": method,
        "legs": [
            [leg["origin_node_id"], leg["destination_node_id"], leg["distance_m"], leg["duration_s"]]
            for leg in legs
        ],
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def _draft_notice(plan) -> str:
    if plan.planning_mode == "coordinate_preview":
        return (
            "Rascunho por coordenadas não homologado: a ordem usa as bases candidatas "
            "da proposta e não altera nenhum status de revisão."
        )
    return (
        "Proposta estrita: a ordem usa as bases candidatas e não altera nenhum "
        "status de revisão."
    )


def _check_matrix_identity(matrix: VehicleMatrix, provider) -> None:
    if provider is None:
        raise VehicleOrderError(MATRIX_MISSING_NOTICE)
    if is_pedestrian_profile(matrix.profile):
        raise VehicleOrderError(
            "A matriz veicular aponta para um perfil pedestre. Gere uma matriz car "
            "própria; o perfil não muda ao chamar /driving em um extrato pedestre."
        )
    if matrix.quality != "network":
        raise VehicleOrderError("A matriz veicular não é de rede; a estimativa é recusada.")
    if (matrix.provider, matrix.profile) != (provider.name, provider.profile):
        raise VehicleOrderError(
            "A matriz veicular pertence a outro provedor ou perfil; gere novamente "
            "com a configuração veicular atual."
        )


def _snapshot_endpoint(snapshot: dict, key: str, role: str) -> VehicleEndpoint:
    entry = snapshot.get(key)
    if not isinstance(entry, dict):
        raise VehicleOrderError(f"A matriz veicular não registra a coordenada de {role}.")
    try:
        return endpoint_from_snapshot(snapshot, key)
    except (KeyError, TypeError, ValueError) as error:
        raise VehicleOrderError(
            f"A matriz veicular registra uma coordenada de {role} inválida."
        ) from error


def validate_matrix_endpoints(
    matrix: VehicleMatrix,
    *,
    origin: VehicleEndpoint,
    destination: VehicleEndpoint,
) -> None:
    """Exige que as coordenadas pedidas sejam as gravadas no snapshot da matriz.

    As coordenadas normalizadas precisam ser idênticas às do snapshot, porque são
    elas que definem o custo; rótulos podem mudar por não participarem do custo.
    Nenhuma estimativa em linha reta entra como fallback.
    """
    snapshot = matrix.input_snapshot
    if not isinstance(snapshot, dict):
        raise VehicleOrderError("A matriz veicular não possui o snapshot esperado.")
    stored_origin = _snapshot_endpoint(snapshot, "origin", "partida")
    stored_destination = _snapshot_endpoint(snapshot, "destination", "chegada")
    for role, stored, requested in (
        ("partida", stored_origin, origin),
        ("chegada", stored_destination, destination),
    ):
        if (stored.latitude, stored.longitude) != (requested.latitude, requested.longitude):
            raise VehicleOrderError(
                f"A coordenada de {role} da requisição divergiu da matriz veicular "
                "informada; gere uma matriz para esta partida e chegada."
            )
    if snapshot["origin"].get("node_id") != ORIGIN_NODE_ID:
        raise VehicleOrderError("O snapshot da matriz não registra o nó de partida esperado.")
    if snapshot["destination"].get("node_id") != DESTINATION_NODE_ID:
        raise VehicleOrderError("O snapshot da matriz não registra o nó de chegada esperado.")


def validate_matrix_points(matrix: VehicleMatrix, expected_point_ids: set[str]) -> None:
    """Exige que os nós de entrega do snapshot sejam os pontos atuais da rota."""
    snapshot = matrix.input_snapshot
    if not isinstance(snapshot, dict):
        raise VehicleOrderError("A matriz veicular não possui o snapshot esperado.")
    point_entries = snapshot.get("points")
    if not isinstance(point_entries, list):
        raise VehicleOrderError("O snapshot da matriz não registra os pontos de entrega esperados.")
    snapshot_point_ids: set[str] = set()
    for entry in point_entries:
        if not isinstance(entry, dict):
            raise VehicleOrderError("O snapshot da matriz contém um ponto de entrega inválido.")
        point_id = entry.get("delivery_point_id")
        if not isinstance(point_id, str) or entry.get("node_id") != delivery_node_id(point_id):
            raise VehicleOrderError("O snapshot da matriz contém um nó de entrega inconsistente.")
        if point_id in snapshot_point_ids:
            raise VehicleOrderError("O snapshot da matriz repete um ponto de entrega.")
        snapshot_point_ids.add(point_id)
    if snapshot_point_ids != set(expected_point_ids):
        raise VehicleOrderError(
            "O snapshot da matriz veicular não corresponde aos pontos de entrega atuais."
        )


def build_vehicle_order(
    session: Session,
    plan,
    *,
    origin: VehicleEndpoint,
    destination: VehicleEndpoint,
    vehicle_provider,
    walking_provider,
    exact_base_limit: int = EXACT_BASE_LIMIT,
    max_points: int = 200,
    vehicle_matrix_id: str | None = None,
) -> dict:
    """Ordem veicular aberta de uma proposta existente, sobre matriz de rede car."""
    if plan.walking_matrix is None or plan.walking_matrix.route_id != plan.route_id:
        raise VehicleOrderError("A proposta não aponta para uma matriz pedestre da mesma rota.")
    if matrix_is_stale(session, plan.walking_matrix, walking_provider):
        raise VehicleOrderError(
            "A proposta está desatualizada; gere outra antes de calcular a ordem veicular."
        )
    origin = validate_endpoint(origin, "partida")
    destination = validate_endpoint(destination, "chegada")

    if vehicle_matrix_id is not None:
        matrix = session.get(VehicleMatrix, vehicle_matrix_id)
        if matrix is None:
            raise VehicleOrderError("Matriz veicular não encontrada; nenhuma conectividade foi presumida.")
        if matrix.route_id != plan.route_id:
            raise VehicleOrderError("A matriz veicular pertence a outra rota.")
        _check_matrix_identity(matrix, vehicle_provider)
        validate_matrix_endpoints(matrix, origin=origin, destination=destination)
        if vehicle_matrix_is_stale(session, matrix, vehicle_provider):
            raise VehicleOrderError("A matriz veicular está desatualizada; gere outra antes da ordem.")
        idempotent = True
    else:
        matrix, idempotent = create_vehicle_matrix(
            session,
            route_id=plan.route_id,
            origin=origin,
            destination=destination,
            provider=vehicle_provider,
            max_points=max_points,
        )
        validate_matrix_endpoints(matrix, origin=origin, destination=destination)

    points = list_delivery_points(session, plan.route_id)
    if not points:
        raise VehicleOrderError("A rota não possui pontos de entrega para a ordem veicular.")
    by_id = {point.id: point for point in points}
    validate_matrix_points(matrix, set(by_id))
    order_key = {
        point.id: (min(package.source_row for package in point.packages), point.id)
        for point in points
    }
    ranks = {
        point_id: index
        for index, point_id in enumerate(sorted(by_id, key=lambda point_id: order_key[point_id]))
    }

    bases = [stop.candidate_base_point_id for stop in plan.stops]
    if not bases:
        raise VehicleOrderError("A proposta não possui macro-paradas para ordenar.")
    if len(bases) != len(set(bases)):
        raise VehicleOrderError("A proposta repete uma base candidata entre macro-paradas.")
    for base in bases:
        if base not in by_id:
            raise VehicleOrderError("Uma macro-parada referencia base de outra rota.")
    assigned = [assignment.delivery_point_id for stop in plan.stops for assignment in stop.assignments]
    if len(assigned) != len(set(assigned)) or set(assigned) != set(by_id):
        raise VehicleOrderError("As macro-paradas não cobrem cada ponto exatamente uma vez.")

    node_ids = {ORIGIN_NODE_ID, DESTINATION_NODE_ID}
    node_ids.update(delivery_node_id(point.id) for point in points)
    costs = _load_costs(session, matrix, node_ids)

    # O solver trabalha com identificadores de nó; os rótulos de endereço e os
    # ids de ponto não participam do custo.
    base_nodes = [delivery_node_id(base) for base in bases]
    node_ranks = {delivery_node_id(point_id): rank for point_id, rank in ranks.items()}
    if len(base_nodes) <= exact_base_limit:
        sequence, distance, duration = _solve_exact(
            ORIGIN_NODE_ID, base_nodes, DESTINATION_NODE_ID, costs, node_ranks
        )
        method, optimal = "exact_dynamic_programming", True
    else:
        sequence, distance, duration = _solve_heuristic(
            ORIGIN_NODE_ID, base_nodes, DESTINATION_NODE_ID, costs, node_ranks
        )
        method, optimal = "heuristic_nearest_neighbor_2opt", False
    legs, distance, duration = _legs(sequence, costs)

    bases_by_node = {delivery_node_id(stop.candidate_base_point_id): stop for stop in plan.stops}
    order = []
    for position, node_id in enumerate(sequence):
        stop = bases_by_node.get(node_id)
        order.append({
            "position": position,
            "node_id": node_id,
            "node_role": node_role(node_id),
            "delivery_point_id": None if stop is None else stop.candidate_base_point_id,
            "stop_id": None if stop is None else stop.id,
            "stop_ordinal": None if stop is None else stop.ordinal,
            "label": origin.label if node_id == ORIGIN_NODE_ID
            else destination.label if node_id == DESTINATION_NODE_ID else None,
        })

    provisional = plan.planning_mode == "coordinate_preview"
    review_counts = {"accepted": 0, "rejected": 0, "pending": 0}
    for stop in plan.stops:
        review_counts[stop.review_status] = review_counts.get(stop.review_status, 0) + 1
    return {
        "plan_id": plan.id,
        "route_id": plan.route_id,
        "vehicle_matrix_id": matrix.id,
        "matrix_provider": matrix.provider,
        "matrix_profile": matrix.profile,
        "matrix_quality": matrix.quality,
        "matrix_dataset_revision": matrix.dataset_revision,
        "planning_mode": plan.planning_mode,
        "provisional_draft": provisional,
        "stale": False,
        "idempotent": idempotent,
        "algorithm_version": ALGORITHM_VERSION,
        "order_rule": ORDER_RULE,
        "distance_basis": DISTANCE_BASIS,
        "exact_base_limit": exact_base_limit,
        "origin": {
            "node_id": ORIGIN_NODE_ID, "latitude": origin.latitude,
            "longitude": origin.longitude, "label": origin.label,
        },
        "destination": {
            "node_id": DESTINATION_NODE_ID, "latitude": destination.latitude,
            "longitude": destination.longitude, "label": destination.label,
        },
        "draft": True,
        "base_status": "unverified",
        "parking_notice": PARKING_NOTICE,
        "gps_notice": GPS_NOTICE,
        "capability_notice": CAPABILITY_NOTICE,
        "heuristic_notice": HEURISTIC_NOTICE,
        "draft_notice": _draft_notice(plan),
        "geometry_available": False,
        "maneuvers_available": False,
        "voice_available": False,
        "base_count": len(bases),
        "package_count": sum(stop.package_count for stop in plan.stops),
        "stop_review_counts": review_counts,
        "exact_coverage": True,
        "solution_method": method,
        "optimal": optimal,
        "total_distance_m": distance,
        "total_duration_s": duration,
        "content_hash": _content_hash(sequence, legs, method),
        "order": order,
        "legs": legs,
    }

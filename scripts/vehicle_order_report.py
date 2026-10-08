"""Rascunho privado da ordem veicular aberta das propostas de macro-paradas.

Usa uma matriz dirigida OSRM de perfil ``car`` com endpoint, revisão e raio
próprios. Nenhuma distância em linha reta ou matriz pedestre substitui a via.
A partida e a chegada são lidas de um arquivo local (``data/`` ou ``outputs/``);
este script não contém coordenadas reais e nunca imprime a URL do banco.

Uso:
    python scripts/vehicle_order_report.py \
        --endpoints-file data/vehicle-endpoints.json \
        --vehicle-base-url http://127.0.0.1:5003 \
        --vehicle-dataset-revision <sha256-do-recorte-car> \
        --ensure-preview-plans \
        --output outputs/ordem-veicular-rascunho-AAAAMMDD.md \
        --json-output outputs/ordem-veicular-rascunho-AAAAMMDD.json
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from sqlalchemy import select

from jet_rapido.database import create_database_engine, create_session_factory
from jet_rapido.maps import MapProviderError, OSRMWalkingProvider
from jet_rapido.macro_service import create_macro_plan, list_macro_plans
from jet_rapido.models import Route, VehicleMatrix, VehicleMatrixEntry, WalkingMatrix
from jet_rapido.repository import list_delivery_points
from jet_rapido.vehicle_service import (
    VehicleEndpoint, VehicleOrderError, build_vehicle_order, vehicle_matrix_is_stale,
)
from jet_rapido.walking_service import matrix_is_stale


class SnapshotProvider:
    """Reproduz a identidade do provedor gravada na matriz, sem consultar a rede.

    Permite avaliar ``matrix_is_stale`` (e criar propostas por coordenadas) sem
    precisar do endpoint pedestre: a comparação vira apenas o estado dos pontos.
    """

    def __init__(self, matrix):
        snapshot = matrix.input_snapshot or {}
        self.name = matrix.provider
        self.profile = matrix.profile
        self.quality = matrix.quality
        self.cache_key = snapshot.get("provider_key") or f"{matrix.provider}:{matrix.profile}"


def load_endpoints(path: Path) -> tuple[VehicleEndpoint, VehicleEndpoint]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    def endpoint(key):
        entry = payload[key]
        return VehicleEndpoint(
            latitude=float(entry["latitude"]),
            longitude=float(entry["longitude"]),
            label=entry.get("label"),
        )
    return endpoint("origin"), endpoint("destination")


def current_network_matrix(session, route_id: str, provider):
    """Matriz pedestre de rede mais recente e ainda atual da rota."""
    matrices = list(session.scalars(
        select(WalkingMatrix)
        .where(WalkingMatrix.route_id == route_id, WalkingMatrix.quality == "network")
        .order_by(WalkingMatrix.created_at.desc())
    ))
    for matrix in matrices:
        if not matrix_is_stale(session, matrix, SnapshotProvider(matrix)):
            return matrix
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default="sqlite:///data/jet_rapido.db")
    parser.add_argument("--endpoints-file", type=Path, required=True)
    parser.add_argument("--vehicle-base-url", required=True)
    parser.add_argument("--vehicle-profile", default="car")
    parser.add_argument("--vehicle-dataset-revision", default="unverified")
    parser.add_argument("--vehicle-snap-radius-m", type=float, default=100.0)
    parser.add_argument("--vehicle-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--exact-base-limit", type=int, default=12)
    parser.add_argument("--max-points", type=int, default=200)
    parser.add_argument("--max-packages", type=int, default=8)
    parser.add_argument("--max-pairwise-m", type=float, default=400.0)
    parser.add_argument("--max-base-roundtrip-m", type=float, default=600.0)
    parser.add_argument("--ensure-preview-plans", action="store_true",
                        help="Cria/reaproveita a proposta por coordenadas de cada rota.")
    parser.add_argument("--route", action="append", default=None)
    parser.add_argument("--plan", action="append", default=None)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("O relatório já existe. Escolha outro arquivo de saída.")
    if args.json_output and args.json_output.exists():
        parser.error("O JSON já existe. Escolha outro arquivo de saída.")

    origin, destination = load_endpoints(args.endpoints_file)
    vehicle = OSRMWalkingProvider(
        base_url=args.vehicle_base_url, profile=args.vehicle_profile,
        timeout_seconds=args.vehicle_timeout_seconds, block_size=50,
        dataset_revision=args.vehicle_dataset_revision,
        snap_radius_m=args.vehicle_snap_radius_m,
    )
    engine = create_database_engine(args.database_url)
    session_factory = create_session_factory(engine)
    results = []
    try:
        with session_factory() as session:
            routes = list(session.scalars(select(Route).order_by(Route.created_at, Route.id)))
            if args.route:
                routes = [route for route in routes if route.id in set(args.route)]
            for route in routes:
                matrix = current_network_matrix(session, route.id, SnapshotProvider)
                if matrix is None:
                    results.append({"route_id": route.id, "status": "sem_matriz_pedestre_atual"})
                    continue
                plan = None
                if args.ensure_preview_plans:
                    points = list_delivery_points(session, route.id)
                    if not points:
                        results.append({"route_id": route.id, "status": "sem_pontos"})
                        continue
                    try:
                        plan, _ = create_macro_plan(
                            session, route_id=route.id, matrix_id=matrix.id,
                            provider=SnapshotProvider(matrix),
                            max_packages=args.max_packages,
                            max_pairwise_m=args.max_pairwise_m,
                            max_base_roundtrip_m=args.max_base_roundtrip_m,
                            planning_mode="coordinate_preview",
                        )
                    except Exception as error:  # proposta recusada por gate da etapa 4
                        results.append({"route_id": route.id, "status": "proposta_recusada",
                                        "detail": str(error)})
                        continue
                plans = list_macro_plans(session, route.id, limit=20, offset=0)
                if args.plan:
                    plans = [item for item in plans if item.id in set(args.plan)]
                if plan is not None:
                    plans = [item for item in plans if item.id == plan.id] or [plan]
                for plan in plans:
                    entry = {
                        "route_id": route.id,
                        "plan_id": plan.id,
                        "planning_mode": plan.planning_mode,
                        "walking_matrix_id": plan.walking_matrix_id,
                        "macro_stop_count": len(plan.stops),
                        "status": "ok",
                    }
                    try:
                        payload = build_vehicle_order(
                            session, plan, origin=origin, destination=destination,
                            vehicle_provider=vehicle,
                            walking_provider=SnapshotProvider(plan.walking_matrix),
                            exact_base_limit=args.exact_base_limit,
                            max_points=args.max_points,
                        )
                    except VehicleOrderError as error:
                        entry["status"] = "recusada"
                        entry["detail"] = str(error)
                        results.append(entry)
                        continue
                    except MapProviderError as error:
                        entry["status"] = "rede_veicular_indisponivel"
                        entry["detail"] = "Falha ao consultar o OSRM car; nenhuma matriz foi fabricada."
                        entry["error"] = type(error).__name__
                        results.append(entry)
                        continue
                    matrix_row = session.get(VehicleMatrix, payload["vehicle_matrix_id"])
                    entries = list(session.scalars(
                        select(VehicleMatrixEntry).where(
                            VehicleMatrixEntry.matrix_id == payload["vehicle_matrix_id"]
                        )
                    ))
                    entry.update({
                        "vehicle_matrix_id": payload["vehicle_matrix_id"],
                        "vehicle_matrix_stale": vehicle_matrix_is_stale(session, matrix_row, vehicle),
                        "matrix_profile": payload["matrix_profile"],
                        "matrix_quality": payload["matrix_quality"],
                        "matrix_dataset_revision": payload["matrix_dataset_revision"],
                        "matrix_point_count": matrix_row.point_count,
                        "matrix_reachable_pairs": matrix_row.reachable_pairs,
                        "matrix_unreachable_pairs": matrix_row.unreachable_pairs,
                        "matrix_entries": len(entries),
                        "base_count": payload["base_count"],
                        "package_count": payload["package_count"],
                        "solution_method": payload["solution_method"],
                        "optimal": payload["optimal"],
                        "total_distance_m": payload["total_distance_m"],
                        "total_duration_s": payload["total_duration_s"],
                        "content_hash": payload["content_hash"],
                        "stop_review_counts": payload["stop_review_counts"],
                        "order": payload["order"],
                        "legs": payload["legs"],
                    })
                    results.append(entry)
    finally:
        engine.dispose()

    computed = [item for item in results if item.get("status") == "ok"]
    header = [
        "# Relatório privado — ordem veicular aberta (rascunho da etapa 5)",
        "",
        "Gerado a partir de matrizes dirigidas OSRM de perfil veicular. A matriz "
        "pedestre não substitui a via e nenhuma distância em linha reta foi usada. "
        "Este arquivo não contém endereços nem coordenadas.",
        "",
        f"- Gerado em: `{datetime.now(timezone.utc).isoformat()}`",
        f"- Perfil veicular: `{args.vehicle_profile}` · revisão do conjunto de dados: "
        f"`{args.vehicle_dataset_revision}`",
        "- Fonte: banco local configurado (URL de conexão omitida por segurança)",
        "",
        "## Resumo",
        "",
        f"- Propostas processadas: {len(results)} ({len(computed)} calculadas)",
        f"- Bases ordenadas: {sum(item['base_count'] for item in computed)} · "
        f"pacotes: {sum(item['package_count'] for item in computed)}",
        f"- Distância dirigida total: {sum(item['total_distance_m'] for item in computed):.1f} m · "
        f"duração total: {sum(item['total_duration_s'] for item in computed):.1f} s",
        f"- Pares sem caminho nas matrizes veiculares: "
        f"{sum(item['matrix_unreachable_pairs'] for item in computed)}",
        "- Rascunho: base candidata não verificada, sem estacionamento confirmado, "
        "geometria, manobras, voz ou economia declarada",
        "",
    ]
    sections = []
    for item in results:
        if item.get("status") != "ok":
            sections.extend([
                f"## Rota `{item['route_id'][:8]}` — {item['status']}",
                "",
                f"- {item.get('detail', 'sem detalhe')}",
                "",
            ])
            continue
        method = "exata" if item["optimal"] else "heurística não ótima"
        sections.extend([
            f"## Rota `{item['route_id'][:8]}` · proposta `{item['plan_id'][:8]}`",
            "",
            f"- Modo: `{item['planning_mode']}` · macro-paradas: {item['macro_stop_count']} · "
            f"bases: {item['base_count']} · pacotes: {item['package_count']}",
            f"- Matriz veicular `{item['vehicle_matrix_id'][:8]}`: "
            f"{item['matrix_profile']}/{item['matrix_quality']} · "
            f"revisão `{item['matrix_dataset_revision']}` · "
            f"{item['matrix_point_count']} nós · {item['matrix_entries']} pares · "
            f"{item['matrix_unreachable_pairs']} sem caminho · "
            f"desatualizada: {item['vehicle_matrix_stale']}",
            f"- Ordem: {item['base_count']} bases visitadas uma vez · solução {method} "
            f"({item['solution_method']}) · distância {item['total_distance_m']:.1f} m · "
            f"duração {item['total_duration_s']:.1f} s · hash `{item['content_hash'][:16]}`",
            f"- Revisão dos agrupamentos: {item['stop_review_counts']}",
            "",
            "| Posição | Papel | Macro-parada |",
            "| ---: | --- | ---: |",
        ])
        for step in item["order"]:
            sections.append(
                f"| {step['position']} | {step['node_role']} | "
                f"{step['stop_ordinal'] if step['stop_ordinal'] is not None else '—'} |"
            )
        sections.extend([
            "",
            "| Perna | Distância (m) | Duração (s) |",
            "| ---: | ---: | ---: |",
        ])
        for leg in item["legs"]:
            sections.append(
                f"| {leg['position']} | {leg['distance_m']:.1f} | {leg['duration_s']:.1f} |"
            )
        sections.append("")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write("\n".join(header + sections) + "\n")
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        with args.json_output.open("x", encoding="utf-8") as stream:
            json.dump({
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "vehicle_profile": args.vehicle_profile,
                "vehicle_dataset_revision": args.vehicle_dataset_revision,
                "results": results,
            }, stream, ensure_ascii=False, indent=2)
    print(f"Relatório privado salvo: {len(computed)}/{len(results)} propostas com ordem veicular.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

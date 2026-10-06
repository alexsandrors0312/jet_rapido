"""Relatório privado e agregado dos circuitos das propostas existentes.

Não contém endereços, coordenadas, códigos de pacote nem o banco. Usa apenas as
matrizes pedestres já persistidas: nenhum OSRM é recalculado e nenhuma distância
em linha reta é usada. Saída em `outputs/`, ignorada pelo Git.

Uso:
    python scripts/circuit_report.py --output outputs/circuitos-rascunho-AAAAMMDD.md
"""
import argparse
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from jet_rapido.circuit_service import CircuitError, build_macro_plan_circuits
from jet_rapido.database import create_database_engine, create_session_factory
from jet_rapido.macro_service import get_macro_plan
from jet_rapido.models import MacroPlan


class SnapshotProvider:
    """Reconstrói a identidade do provedor a partir do snapshot para medir staleness.

    Não consulta a rede: só repete o `cache_key` gravado na matriz, permitindo que
    `matrix_is_stale` seja avaliado sem OSRM disponível.
    """

    def __init__(self, matrix):
        snapshot = matrix.input_snapshot or {}
        self.name = matrix.provider
        self.profile = matrix.profile
        self.quality = matrix.quality
        self.cache_key = snapshot.get("provider_key") or f"{matrix.provider}:{matrix.profile}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default="sqlite:///data/jet_rapido.db")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--plan", action="append", default=None,
                        help="Restringe a propostas específicas (repetível).")
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("O relatório já existe. Escolha outro arquivo de saída.")

    fixed_header = [
        "# Relatório privado — circuitos pedestres fechados (rascunho da etapa 5)",
        "",
        "Gerado a partir das matrizes pedestres já persistidas. Nenhum OSRM foi "
        "recalculado, nenhuma distância em linha reta foi usada e não há endereços, "
        "coordenadas ou códigos de pacote neste arquivo.",
        "",
        f"- Gerado em: `{datetime.now(timezone.utc).isoformat()}`",
        "- Fonte: matrizes pedestres persistidas no banco configurado "
        "(URL de conexão omitida por segurança)",
        "",
    ]
    sections = []
    totals = {"plans": 0, "ok": 0, "refused": 0, "circuits": 0, "exact": 0, "heuristic": 0,
              "exceeding": 0, "distance_m": 0.0, "duration_s": 0.0, "points": 0, "packages": 0}
    engine = create_database_engine(args.database_url)
    session_factory = create_session_factory(engine)
    try:
        with session_factory() as session:
            statement = select(MacroPlan.id).order_by(MacroPlan.created_at, MacroPlan.id)
            if args.plan:
                statement = statement.where(MacroPlan.id.in_(args.plan))
            for plan_id in list(session.scalars(statement)):
                plan = get_macro_plan(session, plan_id)
                matrix = plan.walking_matrix
                totals["plans"] += 1
                block = [f"## Proposta `{plan.id[:8]}`", "",
                         f"- Modo: `{plan.planning_mode}` · matriz `{plan.walking_matrix_id[:8]}` "
                         f"({matrix.quality}, {matrix.point_count} pontos)",
                         f"- Pacotes: {sum(stop.package_count for stop in plan.stops)} · "
                         f"macro-paradas: {len(plan.stops)}"]
                try:
                    payload = build_macro_plan_circuits(session, plan, SnapshotProvider(matrix))
                except CircuitError as error:
                    totals["refused"] += 1
                    sections.extend(block + [f"- RECUSADA: {error}", ""])
                    continue
                totals["ok"] += 1
                totals["circuits"] += payload["circuit_count"]
                totals["exact"] += payload["exact_circuit_count"]
                totals["heuristic"] += payload["heuristic_circuit_count"]
                totals["exceeding"] += payload["circuits_exceeding_base_roundtrip"]
                totals["distance_m"] += payload["total_distance_m"]
                totals["duration_s"] += payload["total_duration_s"]
                totals["points"] += payload["point_count"]
                totals["packages"] += payload["package_count"]
                block.extend([
                    f"- Limite de ida e volta à base (parâmetro da proposta): "
                    f"{payload['max_base_roundtrip_m']:.1f} m por endereço",
                    f"- {payload['base_roundtrip_limit_notice']}",
                    f"- Circuitos: {payload['circuit_count']} "
                    f"({payload['exact_circuit_count']} exatos, "
                    f"{payload['heuristic_circuit_count']} heurísticos não ótimos) · "
                    f"cobertura exata: {payload['exact_coverage']}",
                    f"- Distância dirigida total: {payload['total_distance_m']:.1f} m · "
                    f"duração acumulada total: {payload['total_duration_s']:.1f} s",
                    f"- Circuitos acima do limite de ida e volta à base: "
                    f"{payload['circuits_exceeding_base_roundtrip']}",
                    "",
                    "| Macro-parada | Pontos | Pacotes | Distância (m) | Duração (s) | "
                    "Solução | Supera ida/volta |",
                    "| ---: | ---: | ---: | ---: | ---: | --- | --- |",
                ])
                for circuit in sorted(payload["circuits"], key=lambda item: item["ordinal"]):
                    method = "exata" if circuit["optimal"] else "heurística não ótima"
                    exceeds = "sim, não limita a volta completa" if circuit["exceeds_base_roundtrip_limit"] else "não"
                    block.append(
                        f"| {circuit['ordinal']} | {circuit['point_count']} | "
                        f"{circuit['package_count']} | {circuit['distance_m']:.1f} | "
                        f"{circuit['duration_s']:.1f} | {method} | {exceeds} |"
                    )
                block.append("")
                for circuit in sorted(payload["circuits"], key=lambda item: item["ordinal"]):
                    if circuit["roundtrip_warning"]:
                        block.append(f"> Aviso — {circuit['roundtrip_warning']}")
                if payload["circuits_exceeding_base_roundtrip"]:
                    block.append("")
                sections.extend(block)
    finally:
        engine.dispose()

    summary = [
        "## Resumo",
        "",
        f"- Propostas: {totals['plans']} ({totals['ok']} calculadas, {totals['refused']} recusadas)",
        f"- Circuitos: {totals['circuits']} ({totals['exact']} exatos, "
        f"{totals['heuristic']} heurísticos não ótimos)",
        f"- Circuitos acima do limite de ida e volta à base: {totals['exceeding']} "
        "(o limite vale por ida e volta individual, não para a volta completa)",
        f"- Pontos cobertos: {totals['points']} · pacotes: {totals['packages']}",
        f"- Distância dirigida total: {totals['distance_m']:.1f} m · "
        f"duração acumulada total: {totals['duration_s']:.1f} s",
        "- Base: `unverified` (entrada candidata, não estacionamento) · sem geometria, manobras ou voz",
        "- A partida real deve usar o GPS confirmado do veículo; nenhuma economia operacional é declarada",
        "",
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write("\n".join(fixed_header + summary + sections) + "\n")
    print(f"Relatório privado salvo: {totals['ok']}/{totals['plans']} propostas, "
          f"{totals['circuits']} circuitos, {totals['distance_m']:.1f} m dirigidos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

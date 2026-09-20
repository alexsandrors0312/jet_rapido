"""Relatório local da matriz e dos candidatos de rua dividida; não confirma pontos."""
import argparse
import json
from pathlib import Path
from datetime import datetime, timezone

import httpx2 as httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("route_id")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("O relatório já existe. Escolha outro arquivo de saída.")
    with httpx.Client(base_url=args.api_url, timeout=360) as client:
        def get(path):
            response = client.get(path)
            response.raise_for_status()
            return response.json()
        config = get("/api/v1/maps/config")
        if config["quality"] != "network":
            parser.error("A validação exige um provedor de rede pedestre.")
        route = get(f"/api/v1/routes/{args.route_id}")
        response = client.post(f"/api/v1/routes/{args.route_id}/walking-matrices", json={})
        response.raise_for_status()
        matrix = response.json()
        if matrix["stale"]:
            parser.error("A revisão mudou durante o cálculo. Execute novamente.")
        entries = []
        for offset in range(0, matrix["point_count"] ** 2, 1000):
            entries.extend(get(f"/api/v1/walking-matrices/{matrix['id']}/entries?offset={offset}&limit=1000"))
        streets = {}
        for package in route["packages"]:
            street = streets.setdefault(package["street_key"], {"stops": set(), "points": set()})
            street["stops"].add(package["original_stop"])
            street["points"].add(package["delivery_point_id"])
        split = []
        for key, street in streets.items():
            stops = sorted(stop for stop in street["stops"] if stop is not None)
            if len(stops) < 2:
                continue
            pairs = [entry for entry in entries if entry["origin_delivery_point_id"] in street["points"]
                     and entry["destination_delivery_point_id"] in street["points"]
                     and entry["origin_delivery_point_id"] != entry["destination_delivery_point_id"]]
            split.append({"street_key": key, "original_stops": stops, "directed_pairs": pairs})
        report = {"checked_at": datetime.now(timezone.utc).isoformat(), "matrix": matrix,
                  "split_streets": split, "unreachable_pairs": [entry for entry in entries if not entry["reachable"]],
                  "field_acceptance": "pending — confirmar portões, barreiras e travessias em campo"}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(report, output, ensure_ascii=False, indent=2)
        print(f"Relatório local salvo: {matrix['point_count']} pontos, {matrix['unreachable_pairs']} pares inacessíveis.")


if __name__ == "__main__":
    main()

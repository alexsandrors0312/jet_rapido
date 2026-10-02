"""Audit imported delivery entrances against a local pedestrian OSRM graph.

This is a diagnostic report. Snapping to a road does not confirm a gate,
crossing, or delivery entrance, and this command never edits point reviews.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit

import httpx2 as httpx


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/jet_rapido.db"))
    parser.add_argument("--osrm-url", default="http://127.0.0.1:5000")
    parser.add_argument("--snap-radius-m", type=float, default=50)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if urlsplit(args.osrm_url).hostname not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("A auditoria de dados reais aceita apenas OSRM local.")
    if args.snap_radius_m <= 0 or args.output.exists():
        parser.error("Informe um raio positivo e um arquivo de saída novo.")
    with sqlite3.connect(args.database) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT p.id, p.route_id, p.original_address, p.original_city, "
            "p.effective_latitude, p.effective_longitude, p.review_status, "
            "p.review_source, p.revision, MIN(k.source_row) AS source_row, "
            "COUNT(k.id) AS package_count "
            "FROM delivery_points p JOIN packages k ON k.delivery_point_id = p.id "
            "GROUP BY p.id ORDER BY p.route_id, source_row"
        ).fetchall()
    coordinate_counts = Counter(
        (row["route_id"], row["effective_latitude"], row["effective_longitude"])
        for row in rows
    )
    entries = []
    with httpx.Client(base_url=args.osrm_url, timeout=20) as client:
        for row in rows:
            longitude, latitude = row["effective_longitude"], row["effective_latitude"]
            response = client.get(f"/nearest/v1/foot/{longitude:.7f},{latitude:.7f}",
                                  params={"number": 1, "radiuses": 500})
            response.raise_for_status()
            payload = response.json()
            waypoint = (payload.get("waypoints") or [None])[0]
            snap_distance = waypoint.get("distance") if waypoint else None
            flags = []
            if snap_distance is None:
                flags.append("NO_PEDESTRIAN_SEGMENT_WITHIN_500M")
            elif snap_distance > args.snap_radius_m:
                flags.append("BEYOND_CONFIGURED_SNAP_RADIUS")
            if coordinate_counts[(row["route_id"], latitude, longitude)] > 1:
                flags.append("SHARED_COORDINATE_ACROSS_ADDRESSES")
            entries.append({
                "route_id": row["route_id"], "point_id": row["id"],
                "source_row": row["source_row"], "package_count": row["package_count"],
                "address": row["original_address"], "city": row["original_city"],
                "latitude": latitude, "longitude": longitude,
                "review_status": row["review_status"], "review_source": row["review_source"],
                "revision": row["revision"], "nearest_walkable_m": snap_distance,
                "nearest_way_name": waypoint.get("name") if waypoint else None,
                "flags": flags,
            })
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source": "local_osrm_foot",
        "snap_radius_m": args.snap_radius_m,
        "entries": entries,
        "summary": {
            "point_count": len(entries),
            "pending": sum(entry["review_status"] == "pending" for entry in entries),
            "outside_snap_radius": sum("BEYOND_CONFIGURED_SNAP_RADIUS" in entry["flags"] for entry in entries),
            "no_segment_within_500m": sum("NO_PEDESTRIAN_SEGMENT_WITHIN_500M" in entry["flags"] for entry in entries),
            "shared_coordinates": sum("SHARED_COORDINATE_ACROSS_ADDRESSES" in entry["flags"] for entry in entries),
        },
        "field_acceptance": "pending: confirmar portões e travessias no local",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
    print(json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()

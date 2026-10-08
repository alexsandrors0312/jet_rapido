"""Prepare a small, private OSRM dataset (foot or car) on Windows without Docker.

Requires the separately installed ``osmium`` and ``osrm-bindings`` wheels in a
runtime directory (``data/osrm-tools/runtime`` or one extracted with
``scripts/setup_osrm_runtime.py``). The source PBF is public; the bounding box is
derived locally from delivery points and optional extra coordinates and never
sent to a remote service. The profile fixes the extraction of the graph:
calling a foot dataset with ``/driving`` does not change its costs, so a vehicle
order always needs its own ``car`` dataset and revision.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def route_bounds(database: Path, margin: float) -> tuple[float, float, float, float]:
    connection = sqlite3.connect(database)
    try:
        west, south, east, north = connection.execute(
            "SELECT MIN(effective_longitude), MIN(effective_latitude), "
            "MAX(effective_longitude), MAX(effective_latitude) FROM delivery_points"
        ).fetchone()
    finally:
        connection.close()
    if None in (west, south, east, north):
        raise ValueError("O banco não contém pontos de entrega.")
    return west - margin, south - margin, east + margin, north + margin


def include_points(path: Path) -> list[tuple[float, float]]:
    """Coordinates that must fit inside the crop, e.g. a route start and end.

    Accepts either a list of ``{latitude, longitude}`` objects or the private
    endpoints file shape ``{"origin": {...}, "destination": {...}}``. The values
    are read locally and only the resulting bounds are written to ``data/``.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        entries = [payload[key] for key in ("origin", "destination") if key in payload]
        entries += [value for key, value in payload.items() if key not in ("origin", "destination")]
    elif isinstance(payload, list):
        entries = payload
    else:
        raise ValueError("O arquivo de pontos extras deve ser uma lista ou um objeto JSON.")
    points = []
    for entry in entries:
        if not isinstance(entry, dict) or "latitude" not in entry or "longitude" not in entry:
            raise ValueError("Cada ponto extra exige latitude e longitude.")
        latitude, longitude = float(entry["latitude"]), float(entry["longitude"])
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError("Ponto extra fora dos limites geográficos.")
        points.append((latitude, longitude))
    return points


def expand_bounds(bounds: tuple[float, float, float, float],
                  points: list[tuple[float, float]],
                  margin: float) -> tuple[float, float, float, float]:
    west, south, east, north = bounds
    for latitude, longitude in points:
        west = min(west, longitude - margin)
        east = max(east, longitude + margin)
        south = min(south, latitude - margin)
        north = max(north, latitude + margin)
    return west, south, east, north


def crop(source: Path, target: Path, bounds: tuple[float, float, float, float], osmium) -> None:
    west, south, east, north = bounds
    area_node_ids: set[int] = set()

    class AreaNodes(osmium.SimpleHandler):
        def node(self, node):
            location = node.location
            if location.valid() and west <= location.lon <= east and south <= location.lat <= north:
                area_node_ids.add(node.id)

    AreaNodes().apply_file(str(source))
    if not area_node_ids:
        raise ValueError("Nenhum nó OSM encontrado no recorte.")
    print(f"Nós no recorte: {len(area_node_ids)}", flush=True)

    way_ids: set[int] = set()
    required_node_ids = set(area_node_ids)

    class IntersectingWays(osmium.SimpleHandler):
        def way(self, way):
            if any(node.ref in area_node_ids for node in way.nodes):
                way_ids.add(way.id)
                required_node_ids.update(node.ref for node in way.nodes)

    IntersectingWays().apply_file(str(source))
    print(f"Caminhos no recorte: {len(way_ids)}", flush=True)

    relation_ids: set[int] = set()

    class CompleteRelations(osmium.SimpleHandler):
        def relation(self, relation):
            members = list(relation.members)
            if (any(member.type == "w" and member.ref in way_ids for member in members)
                    and all(member.type != "r" and
                            (member.type != "w" or member.ref in way_ids) for member in members)):
                relation_ids.add(relation.id)
                required_node_ids.update(member.ref for member in members if member.type == "n")

    CompleteRelations().apply_file(str(source))

    class WriteSelected(osmium.SimpleHandler):
        def __init__(self, writer):
            super().__init__()
            self.writer = writer

        def node(self, node):
            if node.id in required_node_ids:
                self.writer.add_node(node)

        def way(self, way):
            if way.id in way_ids:
                self.writer.add_way(way)

        def relation(self, relation):
            if relation.id in relation_ids:
                self.writer.add_relation(relation)

    with osmium.SimpleWriter(str(target)) as writer:
        WriteSelected(writer).apply_file(str(source))
    print(f"Relações completas preservadas: {len(relation_ids)}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Extrato OSM público em .osm.pbf")
    parser.add_argument("--database", type=Path, default=Path("data/jet_rapido.db"))
    parser.add_argument("--runtime", type=Path, default=Path("data/osrm-tools/runtime"))
    parser.add_argument("--output", type=Path, default=Path("data/osrm-walking"))
    parser.add_argument("--margin-degrees", type=float, default=0.025)
    parser.add_argument("--profile", default="foot",
                        help="Perfil de extração do grafo (foot ou car); não muda depois do extract.")
    parser.add_argument("--include-points-file", type=Path, default=None,
                        help="JSON local com coordenadas obrigatórias no recorte (ex.: partida e chegada).")
    args = parser.parse_args()
    if not args.source.is_file() or not args.database.is_file():
        parser.error("Extrato OSM e banco SQLite precisam existir.")
    if args.margin_degrees <= 0:
        parser.error("A margem precisa ser positiva.")
    if args.output.exists():
        parser.error("A pasta de saída já existe; preserve o dataset anterior.")
    runtime = args.runtime.resolve()
    # No Windows as DLLs ficam em pastas ``*.libs``; registrá-las antes do import
    # evita depender de um PATH externo já configurado.
    for library_folder in ("osmium.libs", "osrm_bindings.libs"):
        folder = runtime / library_folder
        if folder.is_dir():
            os.environ["PATH"] = str(folder) + os.pathsep + os.environ.get("PATH", "")
            if hasattr(os, "add_dll_directory"):
                os.add_dll_directory(str(folder))
    sys.path.insert(0, str(runtime))
    try:
        import osmium
    except ImportError as error:
        parser.error(f"Pyosmium não encontrado em {runtime}: {error}")
    profile = runtime / f"share/osrm/profiles/{args.profile}.lua"
    binaries = runtime / "bin"
    if not profile.is_file() or not (binaries / "osrm-extract.exe").is_file():
        parser.error(f"Os executáveis OSRM e o perfil {args.profile}.lua não foram encontrados.")

    bounds = route_bounds(args.database, args.margin_degrees)
    if args.include_points_file is not None:
        extra = include_points(args.include_points_file)
        print(f"Pontos extras no recorte: {len(extra)}", flush=True)
        bounds = expand_bounds(bounds, extra, args.margin_degrees)
    args.output.mkdir(parents=True)
    target = args.output / "map.osm.pbf"
    print("Recortando extrato OSM localmente...", flush=True)
    crop(args.source.resolve(), target.resolve(), bounds, osmium)
    if target.stat().st_size == 0:
        raise RuntimeError("O recorte OSM ficou vazio.")
    environment = os.environ.copy()
    environment["PATH"] = str(runtime / "osrm_bindings.libs") + os.pathsep + environment.get("PATH", "")
    version = subprocess.run([str(binaries / "osrm-extract.exe"), "--version"],
                             check=True, capture_output=True, text=True, env=environment).stdout.strip()
    print(f"Extraindo rede com {args.profile}.lua...", flush=True)
    subprocess.run([str(binaries / "osrm-extract.exe"), "-p", str(profile), str(target)],
                   check=True, env=environment)
    print("Contraindo grafo OSRM...", flush=True)
    subprocess.run([str(binaries / "osrm-contract.exe"), str(args.output / "map.osrm")],
                   check=True, env=environment)
    metadata = {
        "source_sha256": file_sha256(args.source),
        "crop_sha256": file_sha256(target),
        "bounds": bounds,
        "profile": args.profile,
        "osrm_binary_version": version,
    }
    (args.output / "dataset.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"OSRM_DATASET_REVISION={metadata['crop_sha256']}", flush=True)
    print("Extrato e metadados preservados em pasta ignorada pelo Git.", flush=True)


if __name__ == "__main__":
    main()

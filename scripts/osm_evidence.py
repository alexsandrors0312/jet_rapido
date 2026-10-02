"""Evidência OSM local para revisão de entradas — diagnóstico, nunca confirmação.

Cruza os pontos de entrega do banco local com o recorte OSM usado pelo OSRM
(data/osrm-walking/map.osm.pbf): vias nomeadas próximas, números de porta
(addr:housenumber) e alinhamento entre rua do endereço e rua do segmento mais
próximo. Um número de porta ou nome de via no OSM não comprova portão,
travessia segura ou acesso permitido; o relatório serve apenas para decidir
o que o operador precisa verificar em campo.

Funciona sem dependências externas: tenta pyosmium e, se indisponível, usa
um leitor PBF mínimo embutido (adequado ao recorte local de poucos MB).
"""

import argparse
import json
import math
import sqlite3
import struct
import sys
import zlib
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Leitor PBF mínimo (formato OSM PBF 1.4). Usado quando pyosmium não existe.
# ---------------------------------------------------------------------------

def _read_varint(buffer, position):
    result = 0
    shift = 0
    while True:
        byte = buffer[position]
        position += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, position
        shift += 7
        if shift > 70:
            raise ValueError("varint longo demais")


def _zigzag(value):
    return (value >> 1) ^ -(value & 1)


def _parse_message(buffer, position, end):
    """Devolve lista de (field_number, wire_type, value) até o fim do blob."""
    fields = []
    while position < end:
        tag, position = _read_varint(buffer, position)
        field = tag >> 3
        wire = tag & 7
        if wire == 0:  # varint
            value, position = _read_varint(buffer, position)
            fields.append((field, wire, value))
        elif wire == 1:  # 64-bit
            value = struct.unpack_from("<Q", buffer, position)[0]
            position += 8
            fields.append((field, wire, value))
        elif wire == 2:  # length-delimited
            length, position = _read_varint(buffer, position)
            fields.append((field, wire, buffer[position:position + length]))
            position += length
        elif wire == 5:  # 32-bit
            value = struct.unpack_from("<I", buffer, position)[0]
            position += 4
            fields.append((field, wire, value))
        else:
            raise ValueError(f"wire type desconhecido {wire}")
    return fields


def _group_fields(fields):
    grouped = {}
    for field, wire, value in fields:
        grouped.setdefault(field, []).append((wire, value))
    return grouped


def _packed_varints(blob):
    values = []
    position = 0
    while position < len(blob):
        value, position = _read_varint(blob, position)
        values.append(value)
    return values


def iter_pbf_objects(path):
    """Itera PrimitiveBlock do arquivo .osm.pbf, devolvendo (kind, objects)."""
    with path.open("rb") as stream:
        while True:
            header_length_bytes = stream.read(4)
            if not header_length_bytes:
                return
            if len(header_length_bytes) < 4:
                raise ValueError("PBF truncado no cabeçalho.")
            header_length = struct.unpack(">I", header_length_bytes)[0]
            header_blob = stream.read(header_length)
            header_fields = _group_fields(_parse_message(header_blob, 0, len(header_blob)))
            blob_type = header_fields.get(1, [("", "")])[0][1].decode("utf-8", "replace")
            data_size = header_fields.get(3, [(0, 0)])[0][1]
            data = stream.read(data_size)
            blob_fields = _group_fields(_parse_message(data, 0, len(data)))
            raw = b"".join(value for wire, value in blob_fields.get(1, []) if wire == 2)
            if not raw and 3 in blob_fields:
                raw = zlib.decompress(b"".join(value for wire, value in blob_fields[3] if wire == 2))
            if not raw:
                raise ValueError("Blob PBF sem dados brutos.")
            if blob_type == "OSMHeader":
                continue
            block_fields = _group_fields(_parse_message(raw, 0, len(raw)))
            string_table_blob = block_fields.get(1, [(2, b"")])[0][1]
            string_table_fields = _group_fields(
                _parse_message(string_table_blob, 0, len(string_table_blob))
            )
            string_table = [
                value for wire, value in string_table_fields.get(1, []) if wire == 2
            ]
            granularity = block_fields.get(17, [(0, 100)])[0][1] or 100
            lat_offset = block_fields.get(19, [(0, 0)])[0][1]
            lon_offset = block_fields.get(20, [(0, 0)])[0][1]
            groups = [value for wire, value in block_fields.get(2, []) if wire == 2]
            nodes = []
            ways = []
            for group_blob in groups:
                group = _group_fields(_parse_message(group_blob, 0, len(group_blob)))
                # Nós simples
                for wire, value in group.get(1, []):
                    if wire != 2:
                        continue
                    fields = _group_fields(_parse_message(value, 0, len(value)))
                    node_id = fields.get(1, [(0, 0)])[0][1]
                    keys = [string_table[i] for i in _packed_varints(fields[2][0][1])] if 2 in fields else []
                    vals = [string_table[i] for i in _packed_varints(fields[3][0][1])] if 3 in fields else []
                    lat_raw = fields.get(8, [(0, 0)])[0][1]
                    lon_raw = fields.get(9, [(0, 0)])[0][1]
                    lat = 1e-9 * (lat_offset + granularity * _zigzag(lat_raw))
                    lon = 1e-9 * (lon_offset + granularity * _zigzag(lon_raw))
                    tags = {
                        key.decode("utf-8", "replace"): value.decode("utf-8", "replace")
                        for key, value in zip(keys, vals)
                    }
                    nodes.append((node_id, lat, lon, tags))
                # Nós densos
                for wire, value in group.get(2, []):
                    if wire != 2:
                        continue
                    dense = _group_fields(_parse_message(value, 0, len(value)))
                    ids = _packed_varints(dense[1][0][1]) if 1 in dense else []
                    lats = _packed_varints(dense[8][0][1]) if 8 in dense else []
                    lons = _packed_varints(dense[9][0][1]) if 9 in dense else []
                    keys_vals = _packed_varints(dense[10][0][1]) if 10 in dense else []
                    node_id = 0
                    lat = 0
                    lon = 0
                    cursor = 0
                    for index, encoded_id in enumerate(ids):
                        node_id += _zigzag(encoded_id)
                        lat += _zigzag(lats[index])
                        lon += _zigzag(lons[index])
                        tags = {}
                        while cursor < len(keys_vals) and keys_vals[cursor] != 0:
                            key_index = keys_vals[cursor]
                            value_index = keys_vals[cursor + 1]
                            cursor += 2
                            tags[string_table[key_index].decode("utf-8", "replace")] = \
                                string_table[value_index].decode("utf-8", "replace")
                        cursor += 1
                        nodes.append((node_id, 1e-9 * (lat_offset + granularity * lat),
                                      1e-9 * (lon_offset + granularity * lon), tags))
                # Caminhos
                for wire, value in group.get(3, []):
                    if wire != 2:
                        continue
                    fields = _group_fields(_parse_message(value, 0, len(value)))
                    way_id = fields.get(1, [(0, 0)])[0][1]
                    keys = [string_table[i].decode("utf-8", "replace")
                            for i in _packed_varints(fields[2][0][1])] if 2 in fields else []
                    vals = [string_table[i].decode("utf-8", "replace")
                            for i in _packed_varints(fields[3][0][1])] if 3 in fields else []
                    refs_blob = fields.get(8, [(0, b"")])[0][1]
                    refs = []
                    if refs_blob:
                        reference = 0
                        for encoded in _packed_varints(refs_blob):
                            reference += _zigzag(encoded)
                            refs.append(reference)
                    ways.append((way_id, refs, dict(zip(keys, vals))))
            yield "nodes", nodes
            yield "ways", ways


# ---------------------------------------------------------------------------

def point_segment_distance_m(lat, lon, a, b):
    """Distância (m) entre ponto e segmento, aproximação local plana."""
    earth = 6_371_008.8
    rad = math.pi / 180.0
    scale_lon = earth * math.cos(lat * rad)
    px, py = lon * rad * scale_lon, lat * rad * earth
    ax, ay = a[1] * rad * scale_lon, a[0] * rad * earth
    bx, by = b[1] * rad * scale_lon, b[0] * rad * earth
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def load_crop_objects(crop: Path, runtime: Path | None = None):
    """Devolve (node_locations, tagged_nodes, ways) lidos do recorte local."""
    if runtime is not None:
        sys.path.insert(0, str(runtime))
        try:
            import osmium  # noqa: F401
            if hasattr(osmium, "SimpleHandler"):
                return load_crop_with_osmium(crop)
        except ImportError:
            pass
    return load_crop_with_builtin(crop)


def load_crop_with_builtin(crop: Path):
    node_locations = {}
    tagged_nodes = []
    ways = []
    for kind, objects in iter_pbf_objects(crop):
        if kind == "nodes":
            for node_id, lat, lon, tags in objects:
                node_locations[node_id] = (lat, lon)
                if tags:
                    tagged_nodes.append({"lat": lat, "lon": lon, "tags": tags})
        else:
            for way_id, refs, tags in objects:
                geometry = [node_locations.get(ref) for ref in refs]
                geometry = [coord for coord in geometry if coord is not None]
                if len(geometry) >= 2:
                    ways.append({"id": way_id, "tags": tags, "geometry": geometry})
    return node_locations, tagged_nodes, ways


def load_crop_with_osmium(crop: Path):
    import osmium
    node_locations = {}
    tagged_nodes = []
    ways = []

    class NodeHandler(osmium.SimpleHandler):
        def node(self, node):
            location = node.location
            if not location.valid():
                return
            node_locations[node.id] = (location.lat, location.lon)
            tags = {tag.k: tag.v for tag in node.tags}
            if tags:
                tagged_nodes.append({"lat": location.lat, "lon": location.lon, "tags": tags})

    class WayHandler(osmium.SimpleHandler):
        def way(self, way):
            tags = {tag.k: tag.v for tag in way.tags}
            if not tags:
                return
            geometry = [node_locations.get(node.ref) for node in way.nodes]
            geometry = [coord for coord in geometry if coord is not None]
            if len(geometry) >= 2:
                ways.append({"id": way.id, "tags": tags, "geometry": geometry})

    NodeHandler().apply_file(str(crop))
    WayHandler().apply_file(str(crop))
    return node_locations, tagged_nodes, ways


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/jet_rapido.db"))
    parser.add_argument("--crop", type=Path, default=Path("data/osrm-walking/map.osm.pbf"))
    parser.add_argument("--runtime", type=Path, default=Path("data/osrm-tools/runtime"))
    parser.add_argument("--nearby-m", type=float, default=200.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("O relatório já existe. Escolha outro arquivo de saída.")

    with sqlite3.connect(args.database) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT p.id, p.route_id, p.original_address, p.original_city, "
            "p.effective_latitude, p.effective_longitude, p.review_status, "
            "MIN(k.source_row) AS source_row FROM delivery_points p "
            "JOIN packages k ON k.delivery_point_id = p.id "
            "GROUP BY p.id ORDER BY p.route_id, source_row"
        ).fetchall()
    points = [dict(row) for row in rows]

    _node_locations, tagged_nodes, ways = load_crop_objects(args.crop, args.runtime)

    entries = []
    for point in points:
        lat, lon = point["effective_latitude"], point["effective_longitude"]
        nearby_ways = []
        for way in ways:
            tags = way["tags"]
            name = tags.get("name")
            housenumber = tags.get("addr:housenumber")
            if not (name or housenumber or tags.get("highway")):
                continue
            distances = [
                point_segment_distance_m(lat, lon, way["geometry"][i], way["geometry"][i + 1])
                for i in range(len(way["geometry"]) - 1)
            ]
            distance = min(distances)
            if distance <= args.nearby_m:
                nearby_ways.append({
                    "distance_m": round(distance, 1),
                    "name": name,
                    "housenumber": housenumber,
                    "street": tags.get("addr:street"),
                    "highway": tags.get("highway"),
                    "building": tags.get("building"),
                })
        nearby_ways.sort(key=lambda way: way["distance_m"])
        nearby_housenumbers = []
        for node in tagged_nodes:
            tags = node["tags"]
            if not tags.get("addr:housenumber"):
                continue
            distance = math.hypot(
                (node["lat"] - lat) * 111_320.0,
                (node["lon"] - lon) * 111_320.0 * math.cos(math.radians(lat)),
            )
            if distance <= args.nearby_m:
                nearby_housenumbers.append({
                    "distance_m": round(distance, 1),
                    "housenumber": tags.get("addr:housenumber"),
                    "street": tags.get("addr:street"),
                    "name": tags.get("name"),
                })
        nearby_housenumbers.sort(key=lambda node: node["distance_m"])
        entries.append({
            "point_id": point["id"], "route_id": point["route_id"],
            "source_row": point["source_row"], "address": point["original_address"],
            "city": point["original_city"], "latitude": lat, "longitude": lon,
            "review_status": point["review_status"],
            "nearby_ways": nearby_ways[:12],
            "nearby_housenumbers": nearby_housenumbers[:12],
        })

    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source": "local_osm_crop",
        "point_count": len(entries),
        "entries": entries,
        "field_acceptance": "pending — nomes e números no OSM não comprovam portão ou travessia",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
    print(f"Evidência OSM local salva: {len(entries)} pontos analisados.")


if __name__ == "__main__":
    main()

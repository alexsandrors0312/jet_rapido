"""Preparação do conjunto de dados veicular: helpers sintéticos e locais.

Nenhuma coordenada real entra neste arquivo; os testes cobrem apenas a leitura do
arquivo privado de pontos, a união do recorte e a checagem de perfil.
"""

import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepare = load_script("prepare_osrm_windows")
setup_runtime = load_script("setup_osrm_runtime")


class IncludePointsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "points.json"

    def write(self, payload):
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        return self.path

    def test_origin_and_destination_shape_is_accepted(self):
        path = self.write({
            "origin": {"latitude": -23.5, "longitude": -46.6, "label": "partida"},
            "destination": {"latitude": -23.6, "longitude": -46.7},
        })
        points = prepare.include_points(path)
        self.assertEqual(points, [(-23.5, -46.6), (-23.6, -46.7)])

    def test_list_shape_is_accepted(self):
        path = self.write([{"latitude": 1.0, "longitude": 2.0}])
        self.assertEqual(prepare.include_points(path), [(1.0, 2.0)])

    def test_missing_coordinate_is_rejected(self):
        path = self.write([{"latitude": 1.0}])
        with self.assertRaisesRegex(ValueError, "latitude e longitude"):
            prepare.include_points(path)

    def test_out_of_range_coordinate_is_rejected(self):
        path = self.write([{"latitude": 91.0, "longitude": 2.0}])
        with self.assertRaisesRegex(ValueError, "limites geográficos"):
            prepare.include_points(path)

    def test_expand_bounds_unions_every_point_with_margin(self):
        bounds = prepare.expand_bounds((0.0, 0.0, 1.0, 1.0), [(2.0, 3.0), (-1.0, -1.0)], 0.5)
        self.assertEqual(bounds, (-1.5, -1.5, 3.5, 2.5))

    def test_expand_bounds_keeps_original_when_no_extra_points(self):
        self.assertEqual(prepare.expand_bounds((0.0, 0.0, 1.0, 1.0), [], 0.5), (0.0, 0.0, 1.0, 1.0))


class RouteBoundsTests(unittest.TestCase):
    def test_bounds_include_margin_around_every_delivery_point(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "points.db"
            connection = sqlite3.connect(database)
            try:
                connection.execute(
                    "CREATE TABLE delivery_points (effective_latitude REAL, effective_longitude REAL)"
                )
                connection.executemany(
                    "INSERT INTO delivery_points VALUES (?, ?)",
                    [(-23.60, -46.70), (-23.50, -46.60)],
                )
                connection.commit()
            finally:
                connection.close()
            bounds = prepare.route_bounds(database, 0.01)
            for value, expected in zip(bounds, (-46.71, -23.61, -46.59, -23.49)):
                self.assertAlmostEqual(value, expected, places=9)

    def test_empty_database_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "empty.db"
            connection = sqlite3.connect(database)
            try:
                connection.execute(
                    "CREATE TABLE delivery_points (effective_latitude REAL, effective_longitude REAL)"
                )
                connection.commit()
            finally:
                connection.close()
            with self.assertRaisesRegex(ValueError, "não contém pontos"):
                prepare.route_bounds(database, 0.01)


class RuntimeSetupTests(unittest.TestCase):
    def test_required_files_are_declared_for_the_runtime(self):
        # O procedimento precisa dos binários e dos perfis para o extrato veicular.
        for name in ("bin/osrm-extract.exe", "bin/osrm-routed.exe",
                     "share/osrm/profiles/car.lua", "share/osrm/profiles/foot.lua"):
            self.assertIn(name, setup_runtime.REQUIRED)

    def test_prepare_script_accepts_a_profile_and_a_points_file(self):
        source = (ROOT / "scripts" / "prepare_osrm_windows.py").read_text(encoding="utf-8")
        self.assertIn('"--profile"', source)
        self.assertIn('"--include-points-file"', source)
        self.assertIn('"profile": args.profile', source)


if __name__ == "__main__":
    unittest.main()

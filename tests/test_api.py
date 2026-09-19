from pathlib import Path
import tempfile
import unittest

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from jet_rapido.api import create_app
from jet_rapido.config import Settings
from jet_rapido.maps import MatrixCell, MatrixComputation
from jet_rapido.models import Base

from test_importer import fixture, row


ROOT = Path(__file__).resolve().parents[1]


class FakeWalkingProvider:
    name = "fake_network"
    profile = "walking"
    quality = "network"

    def compute(self, points):
        cells = []
        for origin_index, origin in enumerate(points):
            for destination_index, destination in enumerate(points):
                reachable = not (origin_index == 1 and destination_index == 0)
                cells.append(MatrixCell(
                    origin_id=origin.id,
                    destination_id=destination.id,
                    distance_m=float(abs(origin_index - destination_index) * 100) if reachable else None,
                    duration_s=float(abs(origin_index - destination_index) * 80) if reachable else None,
                    reachable=reachable,
                    error_code=None if reachable else "NO_ROUTE",
                ))
        return MatrixComputation(
            provider=self.name,
            profile=self.profile,
            quality=self.quality,
            cells=tuple(cells),
            dataset_version="test-map-v1",
        )


def migrate(database_url: str) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.xlsx = root / "rota.xlsx"
        fixture(self.xlsx, [row(), row("PKG-002", 2, "Avenida Exemplo, 20")])
        self.database_url = f"sqlite:///{(root / 'api.db').as_posix()}"
        migrate(self.database_url)
        self.app = create_app(
            Settings(database_url=self.database_url), walking_provider=FakeWalkingProvider()
        )
        self.addCleanup(self.app.state.engine.dispose)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def upload(self, path: Path | None = None):
        source = path or self.xlsx
        with source.open("rb") as stream:
            return self.client.post(
                "/api/v1/imports",
                files={"file": (source.name, stream, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )

    def test_health_checks_database(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_import_query_and_review_route(self):
        response = self.upload()
        self.assertEqual(response.status_code, 201, response.text)
        imported = response.json()
        self.assertFalse(imported["idempotent"])
        self.assertEqual(imported["package_count"], 2)
        self.assertEqual(len(imported["routes"]), 1)
        self.assertEqual(imported["split_streets"][0]["original_stops"], [1, 2])

        import_response = self.client.get(f"/api/v1/imports/{imported['id']}")
        self.assertEqual(import_response.status_code, 200)
        self.assertEqual(import_response.json()["package_count"], 2)

        route_id = imported["routes"][0]["id"]
        route_response = self.client.get(f"/api/v1/routes/{route_id}")
        self.assertEqual(route_response.status_code, 200)
        self.assertEqual(len(route_response.json()["packages"]), 2)
        self.assertEqual(route_response.json()["packages"][0]["tracking_id"], "PKG-001")

        reviewed = self.client.patch(f"/api/v1/routes/{route_id}/review", json={"reviewed": True})
        self.assertEqual(reviewed.status_code, 200)
        self.assertIsNotNone(reviewed.json()["reviewed_at"])
        unreviewed = self.client.patch(f"/api/v1/routes/{route_id}/review", json={"reviewed": False})
        self.assertIsNone(unreviewed.json()["reviewed_at"])

    def test_same_file_is_idempotent(self):
        first = self.upload()
        second = self.upload()
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertTrue(second.json()["idempotent"])
        routes = self.client.get("/api/v1/routes").json()
        self.assertEqual(len(routes), 1)

    def test_invalid_workbook_leaves_database_unchanged(self):
        bad = Path(self.tmp.name) / "bad.xlsx"
        bad.write_bytes(b"not an xlsx")
        response = self.upload(bad)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.get("/api/v1/routes").json(), [])

    def test_extension_and_size_limits(self):
        text_file = Path(self.tmp.name) / "route.txt"
        text_file.write_bytes(b"hello")
        with text_file.open("rb") as stream:
            response = self.client.post("/api/v1/imports", files={"file": (text_file.name, stream)})
        self.assertEqual(response.status_code, 415)

        small_app = create_app(Settings(database_url=self.database_url, max_upload_bytes=10))
        try:
            with TestClient(small_app) as client, self.xlsx.open("rb") as stream:
                response = client.post("/api/v1/imports", files={"file": ("route.xlsx", stream)})
        finally:
            small_app.state.engine.dispose()
        self.assertEqual(response.status_code, 413)

    def test_unknown_resources_return_404(self):
        self.assertEqual(self.client.get("/api/v1/imports/unknown").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/routes/unknown").status_code, 404)
        self.assertEqual(
            self.client.patch(
                "/api/v1/delivery-points/unknown/review",
                json={"review_status": "confirmed"},
            ).status_code,
            404,
        )
        self.assertEqual(self.client.get("/api/v1/walking-matrices/unknown").status_code, 404)

    def test_geographic_review_and_matrix_lifecycle(self):
        imported = self.upload().json()
        route_id = imported["routes"][0]["id"]
        points_response = self.client.get(f"/api/v1/routes/{route_id}/delivery-points")
        self.assertEqual(points_response.status_code, 200)
        points = points_response.json()
        self.assertEqual(len(points), 2)
        self.assertTrue(all(point["review_status"] == "pending" for point in points))
        self.assertTrue(all(point["package_count"] == 1 for point in points))

        blocked = self.client.post(f"/api/v1/routes/{route_id}/walking-matrices", json={})
        self.assertEqual(blocked.status_code, 409)
        self.assertIn("sem revisão", blocked.json()["detail"])

        confirmation = self.client.post(
            f"/api/v1/routes/{route_id}/delivery-points/confirm-imported"
        )
        self.assertEqual(confirmation.status_code, 200)
        self.assertEqual(confirmation.json()["confirmed_count"], 2)
        self.assertTrue(all(
            point["review_status"] == "confirmed" for point in confirmation.json()["points"]
        ))

        created = self.client.post(f"/api/v1/routes/{route_id}/walking-matrices", json={})
        self.assertEqual(created.status_code, 201, created.text)
        matrix = created.json()
        self.assertFalse(matrix["idempotent"])
        self.assertEqual(matrix["quality"], "network")
        self.assertEqual(matrix["point_count"], 2)
        self.assertEqual(matrix["reachable_pairs"], 3)
        self.assertEqual(matrix["unreachable_pairs"], 1)

        repeated = self.client.post(f"/api/v1/routes/{route_id}/walking-matrices", json={})
        self.assertEqual(repeated.status_code, 200)
        self.assertTrue(repeated.json()["idempotent"])
        self.assertEqual(repeated.json()["id"], matrix["id"])

        entries = self.client.get(
            f"/api/v1/walking-matrices/{matrix['id']}/entries"
        ).json()
        self.assertEqual(len(entries), 4)
        unreachable = [entry for entry in entries if not entry["reachable"]]
        self.assertEqual(len(unreachable), 1)
        self.assertEqual(unreachable[0]["error_code"], "NO_ROUTE")
        self.assertIsNone(unreachable[0]["distance_m"])

        original = points[0]
        corrected = self.client.patch(
            f"/api/v1/delivery-points/{original['id']}/review",
            json={
                "review_status": "corrected",
                "review_source": "operator",
                "review_note": "Entrada fica no portão lateral.",
                "latitude": original["imported_latitude"] + 0.001,
                "longitude": original["imported_longitude"] + 0.001,
            },
        )
        self.assertEqual(corrected.status_code, 200, corrected.text)
        corrected_point = corrected.json()
        self.assertEqual(corrected_point["imported_latitude"], original["imported_latitude"])
        self.assertNotEqual(corrected_point["effective_latitude"], original["imported_latitude"])
        changed_matrix = self.client.post(
            f"/api/v1/routes/{route_id}/walking-matrices", json={}
        )
        self.assertEqual(changed_matrix.status_code, 201)
        self.assertNotEqual(changed_matrix.json()["id"], matrix["id"])

    def test_rejected_point_blocks_matrix_and_review_contract_is_strict(self):
        imported = self.upload().json()
        route_id = imported["routes"][0]["id"]
        point = self.client.get(f"/api/v1/routes/{route_id}/delivery-points").json()[0]
        missing_coordinates = self.client.patch(
            f"/api/v1/delivery-points/{point['id']}/review",
            json={"review_status": "corrected"},
        )
        self.assertEqual(missing_coordinates.status_code, 422)
        extra_coordinates = self.client.patch(
            f"/api/v1/delivery-points/{point['id']}/review",
            json={"review_status": "confirmed", "latitude": -23.5, "longitude": -46.6},
        )
        self.assertEqual(extra_coordinates.status_code, 422)

        rejected = self.client.patch(
            f"/api/v1/delivery-points/{point['id']}/review",
            json={"review_status": "rejected", "review_note": "Coordenada fora do condomínio."},
        )
        self.assertEqual(rejected.status_code, 200)
        blocked = self.client.post(
            f"/api/v1/routes/{route_id}/walking-matrices",
            json={"allow_unreviewed": True},
        )
        self.assertEqual(blocked.status_code, 409)
        self.assertIn("rejeitado", blocked.json()["detail"])

    def test_matrix_size_limit_is_enforced_before_provider_call(self):
        imported = self.upload().json()
        route_id = imported["routes"][0]["id"]
        limited_app = create_app(
            Settings(database_url=self.database_url, max_matrix_points=1),
            walking_provider=FakeWalkingProvider(),
        )
        try:
            with TestClient(limited_app) as client:
                response = client.post(
                    f"/api/v1/routes/{route_id}/walking-matrices",
                    json={"allow_unreviewed": True},
                )
        finally:
            limited_app.state.engine.dispose()
        self.assertEqual(response.status_code, 422)
        self.assertIn("limite configurado", response.json()["detail"])

    def test_same_address_with_conflicting_coordinates_is_flagged(self):
        path = Path(self.tmp.name) / "conflict.xlsx"
        second = row("PKG-002", 2)
        second[8] = -23.499
        fixture(path, [row(), second])
        response = self.upload(path)
        self.assertEqual(response.status_code, 201, response.text)
        result = response.json()
        self.assertEqual(len(result["geographic_issues"]), 1)
        self.assertEqual(result["geographic_issues"][0]["code"], "ADDRESS_COORDINATE_CONFLICT")
        route_id = result["routes"][0]["id"]
        points = self.client.get(f"/api/v1/routes/{route_id}/delivery-points").json()
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["package_count"], 2)

    def test_migration_created_expected_tables(self):
        names = set(inspect(self.app.state.engine).get_table_names())
        self.assertTrue({
            "alembic_version", "import_batches", "routes", "packages", "delivery_points",
            "walking_matrices", "walking_matrix_entries",
        }.issubset(names))
        with self.app.state.engine.connect() as connection:
            differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
        self.assertEqual(differences, [])


if __name__ == "__main__":
    unittest.main()

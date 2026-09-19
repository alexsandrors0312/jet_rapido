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
from jet_rapido.models import Base

from test_importer import fixture, row


ROOT = Path(__file__).resolve().parents[1]


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
        self.app = create_app(Settings(database_url=self.database_url))
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

    def test_migration_created_expected_tables(self):
        names = set(inspect(self.app.state.engine).get_table_names())
        self.assertTrue({"alembic_version", "import_batches", "routes", "packages"}.issubset(names))
        with self.app.state.engine.connect() as connection:
            differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
        self.assertEqual(differences, [])


if __name__ == "__main__":
    unittest.main()

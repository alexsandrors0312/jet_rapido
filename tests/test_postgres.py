"""Executado no CI com um PostgreSQL descartável."""
import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from jet_rapido.api import create_app
from jet_rapido.config import Settings
from test_api import migrate
from test_importer import fixture, row


POSTGRES_URL = os.getenv("JET_RAPIDO_TEST_POSTGRES_URL")


@unittest.skipUnless(POSTGRES_URL, "PostgreSQL de integração não configurado")
class PostgresIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        migrate(POSTGRES_URL)
        cls.app = create_app(Settings(database_url=POSTGRES_URL))
        cls.client = TestClient(cls.app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.app.state.engine.dispose()

    def test_import_is_idempotent_on_postgres(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "route.xlsx"
            suffix = uuid4().hex
            fixture(path, [row(f"PG-{suffix}")])
            content = path.read_bytes()
        files = {"file": ("route.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        first = self.client.post("/api/v1/imports", files=files)
        second = self.client.post("/api/v1/imports", files=files)
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(first.json()["id"], second.json()["id"])
        route_id = first.json()["routes"][0]["id"]
        points = self.client.get(f"/api/v1/routes/{route_id}/delivery-points")
        self.assertEqual(points.status_code, 200, points.text)
        self.assertEqual(len(points.json()), 1)
        confirmation = self.client.post(
            f"/api/v1/routes/{route_id}/delivery-points/confirm-imported"
        )
        self.assertEqual(confirmation.status_code, 200, confirmation.text)
        matrix = self.client.post(f"/api/v1/routes/{route_id}/walking-matrices", json={})
        self.assertEqual(matrix.status_code, 201, matrix.text)
        self.assertEqual(matrix.json()["quality"], "estimate_only")
        self.assertEqual(matrix.json()["reachable_pairs"], 1)


if __name__ == "__main__":
    unittest.main()

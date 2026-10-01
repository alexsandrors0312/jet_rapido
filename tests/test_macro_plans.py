"""A etapa 4 usa somente redes e planilhas sintéticas versionadas."""

from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import text

from jet_rapido.api import create_app
from jet_rapido.config import Settings
from jet_rapido.maps import MatrixCell, MatrixComputation

from test_api import migrate
from test_importer import fixture, row


class SyntheticNetwork:
    name = "synthetic_foot"
    profile = "foot"
    quality = "network"
    cache_key = "synthetic_foot:v1"

    def compute(self, points):
        cells = []
        for origin in points:
            for destination in points:
                a = round((origin.latitude + 23.5) * 1000)
                b = round((destination.latitude + 23.5) * 1000)
                reachable = (a == 10) == (b == 10)
                distance = float(abs(a - b) * 100) if reachable else None
                cells.append(MatrixCell(
                    origin_id=origin.id, destination_id=destination.id,
                    distance_m=distance, duration_s=distance if reachable else None,
                    reachable=reachable, error_code=None if reachable else "NO_ROUTE",
                ))
        return MatrixComputation(provider=self.name, profile=self.profile, quality=self.quality,
                                 cells=tuple(cells), dataset_version="synthetic-v1")


class MacroPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.xlsx = root / "synthetic.xlsx"
        records = [
            row("PKG-001", 1, "Av. Exemplo, 10"),
            row("PKG-002", 1, "Av. Exemplo, 10"),
            row("PKG-003", 2, "Av. Exemplo, 20"),
            row("PKG-004", "-", "Av. Exemplo, 30"),
            row("PKG-005", 4, "Av. Exemplo, 40"),
        ]
        for record, offset in zip(records, (0, 0, 1, 2, 10)):
            record[8] = -23.5 + offset / 1000
        fixture(self.xlsx, records)
        database_url = f"sqlite:///{(root / 'test.db').as_posix()}"
        migrate(database_url)
        self.app = create_app(Settings(database_url=database_url), walking_provider=SyntheticNetwork())
        self.addCleanup(self.app.state.engine.dispose)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        with self.xlsx.open("rb") as stream:
            imported = self.client.post("/api/v1/imports", files={"file": ("synthetic.xlsx", stream)}).json()
        self.route_id = imported["routes"][0]["id"]
        self.client.post(f"/api/v1/routes/{self.route_id}/delivery-points/confirm-imported")
        self.matrix = self.client.post(f"/api/v1/routes/{self.route_id}/walking-matrices", json={}).json()

    def create_plan(self, **changes):
        command = {"walking_matrix_id": self.matrix["id"], "max_packages": 3,
                   "max_pairwise_m": 150, "max_base_roundtrip_m": 250}
        command.update(changes)
        return self.client.post(f"/api/v1/routes/{self.route_id}/macro-plans", json=command)

    def test_exact_coverage_limits_unreachable_and_idempotence(self):
        response = self.create_plan()
        self.assertEqual(response.status_code, 201, response.text)
        plan = response.json()
        self.assertTrue(plan["exact_coverage"])
        self.assertEqual(plan["package_count"], 5)
        self.assertEqual(plan["point_count"], 4)
        self.assertEqual(plan["macro_stop_count"], 3)
        self.assertEqual(plan["original_stop_count"], 3)
        self.assertEqual(plan["packages_without_original_stop"], 1)
        self.assertFalse(plan["distance_comparison_available"])
        self.assertEqual(sorted(stop["package_count"] for stop in plan["stops"]), [1, 1, 3])
        self.assertTrue(any(stop["original_stops"] == [4] and stop["package_count"] == 1
                            for stop in plan["stops"]))
        self.assertTrue(all(stop["max_pairwise_m"] <= 150 and
                            stop["max_base_roundtrip_m"] <= 250 and
                            stop["parking_status"] == "unverified" for stop in plan["stops"]))
        self.assertEqual(len({point for stop in plan["stops"] for point in stop["delivery_point_ids"]}), 4)
        repeated = self.create_plan()
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(repeated.json()["id"], plan["id"])
        self.assertTrue(repeated.json()["idempotent"])
        self.assertEqual(len(self.client.get(f"/api/v1/routes/{self.route_id}/macro-plans").json()), 1)

    def test_review_and_stale_plan(self):
        plan = self.create_plan().json()
        stop = plan["stops"][0]
        reviewed = self.client.patch(f"/api/v1/macro-stops/{stop['id']}/review",
                                     json={"review_status": "accepted", "review_note": "Agrupamento conferido."})
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        self.assertEqual(reviewed.json()["stops"][0]["review_status"], "accepted")
        self.assertEqual(reviewed.json()["stops"][0]["parking_status"], "unverified")
        point = self.client.get(f"/api/v1/routes/{self.route_id}/delivery-points").json()[0]
        correction = self.client.patch(f"/api/v1/delivery-points/{point['id']}/review", json={
            "review_status": "corrected", "expected_revision": point["revision"],
            "latitude": point["effective_latitude"] + .0001,
            "longitude": point["effective_longitude"],
        })
        self.assertEqual(correction.status_code, 200, correction.text)
        self.assertTrue(self.client.get(f"/api/v1/macro-plans/{plan['id']}").json()["stale"])
        self.assertEqual(self.create_plan().status_code, 409)
        self.assertEqual(self.client.patch(f"/api/v1/macro-stops/{stop['id']}/review",
                                           json={"review_status": "accepted"}).status_code, 409)

    def test_capacity_and_matrix_quality_are_hard_gates(self):
        self.assertEqual(self.create_plan(max_packages=1).status_code, 409)
        self.assertEqual(self.create_plan(max_packages=0).status_code, 422)
        self.assertEqual(self.create_plan(max_pairwise_m=-1).status_code, 422)
        from jet_rapido.maps import StraightLineWalkingProvider
        self.app.state.walking_provider = StraightLineWalkingProvider()
        estimate = self.client.post(f"/api/v1/routes/{self.route_id}/walking-matrices", json={}).json()
        estimate_plan = self.client.post(f"/api/v1/routes/{self.route_id}/macro-plans",
                                         json={"walking_matrix_id": estimate["id"]})
        self.assertEqual(estimate_plan.status_code, 409)
        self.assertIn("matriz de rede", estimate_plan.json()["detail"])

    def test_incomplete_matrix_cannot_create_a_plan(self):
        with self.app.state.engine.begin() as connection:
            connection.execute(text("DELETE FROM walking_matrix_entries WHERE id = "
                                    "(SELECT MIN(id) FROM walking_matrix_entries)"))
        response = self.create_plan()
        self.assertEqual(response.status_code, 409)
        self.assertIn("não cobre todos os pares", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()

"""A etapa 4 usa somente redes e planilhas sintéticas versionadas."""

from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import text

from jet_rapido.api import create_app
from jet_rapido.config import Settings
from jet_rapido.macro_service import ALGORITHM_VERSION
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
            row("PKG-003", 2, "Rua Travessa, 20"),
            row("PKG-004", "-", "Rua Segunda, 30"),
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
        self.assertEqual(plan["multi_address_stop_count"], 1)
        self.assertEqual(plan["single_address_stop_count"], 2)
        self.assertEqual(plan["cross_street_stop_count"], 1)
        self.assertEqual(plan["packages_in_multi_address_stops"], 3)
        self.assertEqual(plan["original_stop_count"], 3)
        self.assertEqual(plan["packages_without_original_stop"], 1)
        self.assertFalse(plan["distance_comparison_available"])
        self.assertEqual(sorted(stop["package_count"] for stop in plan["stops"]), [1, 1, 3])
        self.assertTrue(any(stop["original_stops"] == [4] and stop["package_count"] == 1
                            for stop in plan["stops"]))
        self.assertTrue(any(stop["stop_type"] == "multi_address_walk_candidate" and
                            stop["street_count"] == 2 for stop in plan["stops"]))
        self.assertTrue(all(stop["max_pairwise_m"] <= 150 and
                            stop["max_base_roundtrip_m"] <= 250 and
                            stop["parking_status"] == "unverified" for stop in plan["stops"]))
        self.assertEqual(len({point for stop in plan["stops"] for point in stop["delivery_point_ids"]}), 4)
        repeated = self.create_plan()
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(repeated.json()["id"], plan["id"])
        self.assertTrue(repeated.json()["idempotent"])
        self.assertEqual(len(self.client.get(f"/api/v1/routes/{self.route_id}/macro-plans").json()), 1)

    def legacy_input_hash(self, **changes):
        # A API desserializa os limites como float; o hash legado usa esses valores.
        command = {"max_packages": 3, "max_pairwise_m": 150.0, "max_base_roundtrip_m": 250.0}
        command.update(changes)
        legacy_input = {
            "algorithm": ALGORITHM_VERSION,
            "matrix_id": self.matrix["id"],
            "matrix_input_hash": self.matrix["input_hash"],
            **command,
        }
        return sha256(json.dumps(legacy_input, sort_keys=True).encode()).hexdigest()

    def test_legacy_strict_plan_is_found_by_old_hash_without_touching_preview(self):
        legacy_hash = self.legacy_input_hash()
        with self.app.state.engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO macro_plans (id, route_id, walking_matrix_id, input_hash, planning_mode, "
                "max_packages, max_pairwise_m, max_base_roundtrip_m, created_at) "
                "VALUES ('legacy-plan', :route, :matrix, :hash, 'strict', 3, 150, 250, :now)"
            ), {"route": self.route_id, "matrix": self.matrix["id"], "hash": legacy_hash,
                "now": "2026-10-01T12:00:00+00:00"})

        # O hash antigo (sem planning_mode) devolve o plano estrito migrado.
        response = self.create_plan()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["idempotent"])
        self.assertEqual(response.json()["id"], "legacy-plan")
        self.assertEqual(response.json()["planning_mode"], "strict")

        # O rascunho por coordenadas tem hash próprio e não reutiliza o plano estrito.
        preview = self.create_plan(planning_mode="coordinate_preview")
        self.assertEqual(preview.status_code, 201, preview.text)
        self.assertNotEqual(preview.json()["id"], "legacy-plan")
        self.assertEqual(preview.json()["planning_mode"], "coordinate_preview")
        self.assertNotEqual(preview.json()["input_hash"], legacy_hash)

        listed = self.client.get(f"/api/v1/routes/{self.route_id}/macro-plans").json()
        self.assertEqual({plan["id"] for plan in listed}, {"legacy-plan", preview.json()["id"]})

    def test_legacy_plan_without_snapshot_signalizes_current_counts(self):
        plan = self.create_plan().json()
        with self.app.state.engine.begin() as connection:
            connection.execute(text(
                "UPDATE walking_matrices SET input_snapshot = NULL WHERE id = :matrix"
            ), {"matrix": self.matrix["id"]})
        legacy = self.client.get(f"/api/v1/macro-plans/{plan['id']}").json()
        self.assertTrue(legacy["stale"])
        self.assertEqual(legacy["review_counts_basis"], "legacy_current_points")
        self.assertIn("Sem snapshot de entrada", legacy["review_notice"])
        self.assertEqual(legacy["reviewed_point_count"], 4)

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


class CoordinatePreviewTests(unittest.TestCase):
    """O modo por coordenadas é explícito, provisório e não altera revisões."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.xlsx = root / "synthetic.xlsx"
        records = [
            row("PKG-001", 1, "Av. Exemplo, 10"),
            row("PKG-002", 1, "Av. Exemplo, 10"),
            row("PKG-003", 2, "Rua Travessa, 20"),
            row("PKG-004", "-", "Rua Segunda, 30"),
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
        # Nenhum ponto é confirmado: a matriz de rede é provisória por diagnóstico.
        self.matrix = self.client.post(
            f"/api/v1/routes/{self.route_id}/walking-matrices", json={"allow_unreviewed": True}
        ).json()

    def create_plan(self, **changes):
        command = {"walking_matrix_id": self.matrix["id"], "max_packages": 3,
                   "max_pairwise_m": 150, "max_base_roundtrip_m": 250}
        command.update(changes)
        return self.client.post(f"/api/v1/routes/{self.route_id}/macro-plans", json=command)

    def points(self):
        return self.client.get(f"/api/v1/routes/{self.route_id}/delivery-points").json()

    def test_default_mode_refuses_pending_and_preview_accepts(self):
        strict = self.create_plan()
        self.assertEqual(strict.status_code, 409, strict.text)
        self.assertIn("Confirme ou corrija", strict.json()["detail"])

        response = self.create_plan(planning_mode="coordinate_preview")
        self.assertEqual(response.status_code, 201, response.text)
        plan = response.json()
        self.assertEqual(plan["planning_mode"], "coordinate_preview")
        self.assertTrue(plan["provisional_draft"])
        self.assertEqual(plan["pending_point_count"], 4)
        self.assertEqual(plan["reviewed_point_count"], 0)
        self.assertIn("não homologado", plan["review_notice"])
        self.assertTrue(plan["exact_coverage"])
        self.assertEqual(plan["package_count"], 5)
        self.assertEqual(plan["point_count"], 4)
        self.assertTrue(all(stop["parking_status"] == "unverified" for stop in plan["stops"]))

        # O modo por coordenadas não altera o status de revisão dos pontos.
        self.assertTrue(all(point["review_status"] == "pending" for point in self.points()))

        repeated = self.create_plan(planning_mode="coordinate_preview")
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(repeated.json()["id"], plan["id"])
        self.assertTrue(repeated.json()["idempotent"])
        self.assertEqual(len(self.client.get(f"/api/v1/routes/{self.route_id}/macro-plans").json()), 1)

    def test_preview_still_refuses_rejected_points(self):
        point = self.points()[0]
        rejected = self.client.patch(
            f"/api/v1/delivery-points/{point['id']}/review",
            json={"review_status": "rejected", "review_note": "Coordenada inutilizável."},
        )
        self.assertEqual(rejected.status_code, 200, rejected.text)
        response = self.create_plan(planning_mode="coordinate_preview")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("rejeitado", response.json()["detail"])

    def test_preview_refuses_invalid_effective_coordinates(self):
        point = self.points()[0]
        with self.app.state.engine.begin() as connection:
            connection.execute(text("UPDATE delivery_points SET effective_latitude = 999 WHERE id = :id"),
                               {"id": point["id"]})
        response = self.create_plan(planning_mode="coordinate_preview")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("coordenadas efetivas inválidas", response.json()["detail"])

    def test_preview_refuses_estimate_only_and_incomplete_matrix(self):
        from jet_rapido.maps import StraightLineWalkingProvider
        self.app.state.walking_provider = StraightLineWalkingProvider()
        estimate = self.client.post(
            f"/api/v1/routes/{self.route_id}/walking-matrices", json={"allow_unreviewed": True}
        ).json()
        estimate_plan = self.create_plan(walking_matrix_id=estimate["id"], planning_mode="coordinate_preview")
        self.assertEqual(estimate_plan.status_code, 409, estimate_plan.text)
        self.assertIn("matriz de rede", estimate_plan.json()["detail"])

        self.app.state.walking_provider = SyntheticNetwork()
        with self.app.state.engine.begin() as connection:
            connection.execute(text(
                "DELETE FROM walking_matrix_entries WHERE matrix_id = :matrix "
                "AND id = (SELECT MIN(id) FROM walking_matrix_entries WHERE matrix_id = :matrix)"
            ), {"matrix": self.matrix["id"]})
        incomplete = self.create_plan(planning_mode="coordinate_preview")
        self.assertEqual(incomplete.status_code, 409, incomplete.text)
        self.assertIn("não cobre todos os pares", incomplete.json()["detail"])

    def test_strict_and_preview_are_distinct_idempotent_plans(self):
        self.client.post(f"/api/v1/routes/{self.route_id}/delivery-points/confirm-imported")
        matrix = self.client.post(f"/api/v1/routes/{self.route_id}/walking-matrices", json={}).json()
        self.assertFalse(matrix["stale"])
        strict = self.create_plan(walking_matrix_id=matrix["id"])
        self.assertEqual(strict.status_code, 201, strict.text)
        self.assertFalse(strict.json()["provisional_draft"])
        self.assertEqual(strict.json()["pending_point_count"], 0)
        preview = self.create_plan(walking_matrix_id=matrix["id"], planning_mode="coordinate_preview")
        self.assertEqual(preview.status_code, 201, preview.text)
        self.assertTrue(preview.json()["provisional_draft"])
        self.assertNotEqual(strict.json()["id"], preview.json()["id"])
        self.assertNotEqual(strict.json()["input_hash"], preview.json()["input_hash"])
        self.assertTrue(self.create_plan(walking_matrix_id=matrix["id"]).json()["idempotent"])
        self.assertTrue(self.create_plan(
            walking_matrix_id=matrix["id"], planning_mode="coordinate_preview"
        ).json()["idempotent"])
        self.assertEqual(len(self.client.get(f"/api/v1/routes/{self.route_id}/macro-plans").json()), 2)

    def test_preview_is_stale_after_coordinate_update(self):
        plan = self.create_plan(planning_mode="coordinate_preview").json()
        point = self.points()[0]
        correction = self.client.patch(f"/api/v1/delivery-points/{point['id']}/review", json={
            "review_status": "corrected", "expected_revision": point["revision"],
            "latitude": point["effective_latitude"] + 0.0001,
            "longitude": point["effective_longitude"],
        })
        self.assertEqual(correction.status_code, 200, correction.text)
        self.assertTrue(self.client.get(f"/api/v1/macro-plans/{plan['id']}").json()["stale"])
        again = self.create_plan(planning_mode="coordinate_preview")
        self.assertEqual(again.status_code, 409, again.text)
        self.assertIn("desatualizada", again.json()["detail"])

    def test_counts_and_notice_come_from_creation_snapshot_after_review(self):
        plan = self.create_plan(planning_mode="coordinate_preview").json()
        self.assertEqual(plan["pending_point_count"], 4)
        self.assertEqual(plan["reviewed_point_count"], 0)
        self.assertEqual(plan["review_counts_basis"], "plan_input_snapshot")
        original_notice = plan["review_notice"]
        self.assertIn("na entrada da proposta", original_notice)

        point = self.points()[0]
        confirmed = self.client.patch(
            f"/api/v1/delivery-points/{point['id']}/review",
            json={"review_status": "confirmed", "expected_revision": point["revision"]},
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)

        # O estado atual mudou, mas a proposta stale mantém as contagens de origem.
        current = self.points()
        self.assertEqual(sum(p["review_status"] == "pending" for p in current), 3)
        self.assertEqual(sum(p["review_status"] in ("confirmed", "corrected") for p in current), 1)

        stale = self.client.get(f"/api/v1/macro-plans/{plan['id']}").json()
        self.assertTrue(stale["stale"])
        self.assertEqual(stale["pending_point_count"], 4)
        self.assertEqual(stale["reviewed_point_count"], 0)
        self.assertEqual(stale["review_counts_basis"], "plan_input_snapshot")
        self.assertEqual(stale["review_notice"], original_notice)

    def test_panel_and_openapi_expose_coordinate_preview(self):
        console = self.client.get("/")
        self.assertEqual(console.status_code, 200)
        self.assertIn("coordinate_preview", console.text)
        self.assertIn("macro-mode", console.text)
        script = self.client.get("/static/review.js")
        self.assertIn("planning_mode", script.text)
        schema = self.client.get("/openapi.json").json()
        planning_mode = schema["components"]["schemas"]["MacroPlanCreateRequest"]["properties"]["planning_mode"]
        self.assertEqual(planning_mode["default"], "strict")
        self.assertEqual(planning_mode["enum"], ["strict", "coordinate_preview"])
        plan_fields = schema["components"]["schemas"]["MacroPlanResponse"]["properties"]
        self.assertIn("provisional_draft", plan_fields)
        self.assertIn("pending_point_count", plan_fields)
        self.assertIn("review_counts_basis", plan_fields)


if __name__ == "__main__":
    unittest.main()

"""Ordem veicular aberta: rede car e planilhas sintéticas versionadas.

Nenhum dado real entra neste arquivo. Os custos veiculares vêm de uma rede
sintética dirigida de perfil ``car``; o agrupamento das macro-paradas usa uma
rede pedestre sintética separada.
"""

from pathlib import Path
import json
import tempfile
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import text

from jet_rapido.api import create_app
from jet_rapido.config import Settings
from jet_rapido.maps import MapProviderError, MatrixCell, MatrixComputation
from jet_rapido.vehicle_service import (
    EXACT_BASE_LIMIT, ORIGIN_NODE_ID, DESTINATION_NODE_ID, VehicleOrderError,
    delivery_node_id, _path_cost, _solve_exact, _solve_heuristic,
)

from test_api import migrate
from test_circuits import ScriptedNetwork, full_matrix
from test_importer import fixture, row


class ScriptedCarNetwork:
    """Rede veicular sintética: custos dirigidos explícitos por deslocamento."""

    name = "scripted_car"
    profile = "car"
    quality = "network"
    cache_key = "scripted_car:v1"
    dataset_revision = "synthetic-car-v1"

    def __init__(self, values, *, unreachable=()):
        self.values = dict(values)
        self.unreachable = set(unreachable)

    def compute(self, points):
        offsets = {point.id: round((point.latitude + 23.5) * 1000) for point in points}
        cells = []
        for origin in points:
            for destination in points:
                key = (offsets[origin.id], offsets[destination.id])
                if key in self.unreachable:
                    cells.append(MatrixCell(
                        origin_id=origin.id, destination_id=destination.id,
                        distance_m=None, duration_s=None, reachable=False, error_code="NO_ROUTE",
                    ))
                    continue
                distance, duration = self.values[key]
                cells.append(MatrixCell(
                    origin_id=origin.id, destination_id=destination.id,
                    distance_m=distance, duration_s=duration, reachable=True, error_code=None,
                ))
        return MatrixComputation(
            provider=self.name, profile=self.profile, quality=self.quality,
            cells=tuple(cells), dataset_version=self.dataset_revision,
        )


class FailingCarNetwork(ScriptedCarNetwork):
    def compute(self, points):
        raise MapProviderError("rede veicular indisponível no teste")


def values(indices, distance=10.0, duration=None):
    duration = distance if duration is None else duration
    return {
        (origin, destination): (
            0.0 if origin == destination else float(distance),
            0.0 if origin == destination else float(duration),
        )
        for origin in indices for destination in indices
    }


def foot_network(indices, pairwise=500.0):
    """Rede pedestre que mantém cada ponto separado quando o limite é pequeno."""
    return ScriptedNetwork(full_matrix(indices, lambda a, b: 0 if a == b else pairwise))


class VehicleOrderTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.counter = 0
        self.app = None
        self.client = None

    def new_app(self, walking, vehicle):
        self.counter += 1
        database_url = f"sqlite:///{(self.root / f'db-{self.counter}.db').as_posix()}"
        migrate(database_url)
        self.app = create_app(
            Settings(database_url=database_url), walking_provider=walking,
            vehicle_provider=vehicle,
        )
        self.addCleanup(self.app.state.engine.dispose)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def import_route(self, packages, offsets, *, confirm=True, allow_unreviewed=True,
                     compute_matrix=True):
        self.counter += 1
        records = [row(tracking, stop, address) for tracking, stop, address in packages]
        for record, offset in zip(records, offsets):
            record[8] = -23.5 + offset / 1000
        path = self.root / f"route-{self.counter}.xlsx"
        fixture(path, records)
        with path.open("rb") as stream:
            imported = self.client.post(
                "/api/v1/imports", files={"file": ("synthetic.xlsx", stream)}
            ).json()
        route_id = imported["routes"][0]["id"]
        if confirm:
            response = self.client.post(f"/api/v1/routes/{route_id}/delivery-points/confirm-imported")
            self.assertEqual(response.status_code, 200, response.text)
        matrix = None
        if compute_matrix:
            response = self.client.post(
                f"/api/v1/routes/{route_id}/walking-matrices",
                json={"allow_unreviewed": allow_unreviewed},
            )
            self.assertIn(response.status_code, (200, 201), response.text)
            matrix = response.json()
        return route_id, matrix

    def create_plan(self, route_id, matrix_id, **changes):
        command = {"walking_matrix_id": matrix_id, "max_packages": 50,
                   "max_pairwise_m": 1, "max_base_roundtrip_m": 10_000}
        command.update(changes)
        return self.client.post(f"/api/v1/routes/{route_id}/macro-plans", json=command)

    def offsets(self, route_id):
        points = self.client.get(f"/api/v1/routes/{route_id}/delivery-points").json()
        return {point["id"]: round((point["effective_latitude"] + 23.5) * 1000)
                for point in points}

    def order_body(self, plan_id, origin, destination, *, labels=("Saída teste", "Chegada teste"),
                   matrix_id=None):
        body = {
            "plan_id": plan_id,
            "origin": {"latitude": -23.5 + origin / 1000, "longitude": -46.6, "label": labels[0]},
            "destination": {"latitude": -23.5 + destination / 1000, "longitude": -46.6,
                            "label": labels[1]},
        }
        if matrix_id is not None:
            body["vehicle_matrix_id"] = matrix_id
        return body

    def create_order(self, route_id, plan_id, origin, destination, **kwargs):
        return self.client.post(
            f"/api/v1/routes/{route_id}/vehicle-orders",
            json=self.order_body(plan_id, origin, destination, **kwargs),
        )

    def create_vehicle_matrix(self, route_id, origin, destination):
        body = self.order_body("", origin, destination)
        return self.client.post(
            f"/api/v1/routes/{route_id}/vehicle-matrices",
            json={"origin": body["origin"], "destination": body["destination"]},
        )

    def sequence_offsets(self, data, route_id, origin, destination):
        delivery = {delivery_node_id(point_id): offset for point_id, offset in self.offsets(route_id).items()}
        resolved = {ORIGIN_NODE_ID: origin, DESTINATION_NODE_ID: destination, **delivery}
        return [resolved[step["node_id"]] for step in data["order"]]


class DirectedOpenOrderTests(VehicleOrderTestBase):
    def test_open_order_is_not_the_trivial_sequence(self):
        # Base A é a canônica, mas o caminho ótimo termina a visita na ordem inversa.
        car = ScriptedCarNetwork(values([-1, 0, 1, 2, 3], distance=100.0))
        for key, value in {
            (-1, 0): (10, 10), (-1, 1): (10, 10), (-1, 2): (1, 1), (-1, 3): (100, 100),
            (2, 1): (1, 1), (1, 0): (1, 1), (0, 3): (1, 1),
        }.items():
            car.values[key] = value
        walking = foot_network([0, 1, 2])
        self.new_app(walking, car)
        route_id, matrix = self.import_route(
            [("PKG-001", 1, "Rua A, 1"), ("PKG-002", 2, "Rua B, 2"), ("PKG-003", 3, "Rua C, 3")],
            [0, 1, 2],
        )
        plan = self.create_plan(route_id, matrix["id"]).json()
        self.assertEqual(plan["macro_stop_count"], 3)
        response = self.create_order(route_id, plan["id"], -1, 3)
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(self.sequence_offsets(data, route_id, -1, 3), [-1, 2, 1, 0, 3])
        self.assertEqual(data["total_distance_m"], 4)
        self.assertEqual(data["total_duration_s"], 4)
        self.assertTrue(data["optimal"])
        self.assertEqual(data["solution_method"], "exact_dynamic_programming")
        self.assertEqual(len(data["legs"]), 4)
        self.assertEqual(data["legs"][0]["origin_node_id"], ORIGIN_NODE_ID)
        self.assertEqual(data["legs"][0]["origin_role"], "origin")
        self.assertEqual(data["legs"][-1]["destination_node_id"], DESTINATION_NODE_ID)
        self.assertEqual(data["legs"][-1]["destination_role"], "destination")
        # As pernas refletem exatamente a sequência escolhida.
        ordered = [step["node_id"] for step in data["order"]]
        for index, leg in enumerate(data["legs"]):
            self.assertEqual(leg["origin_node_id"], ordered[index])
            self.assertEqual(leg["destination_node_id"], ordered[index + 1])

    def test_duration_breaks_a_distance_tie_on_the_same_sequence(self):
        car = ScriptedCarNetwork(values([-1, 0, 1, 2], distance=100.0, duration=100.0))
        for key, value in {
            (-1, 0): (1, 1), (-1, 1): (1, 1),
            (0, 1): (1, 1), (1, 0): (1, 1),
            (0, 2): (5, 10), (1, 2): (5, 1),
        }.items():
            car.values[key] = value
        walking = foot_network([0, 1])
        self.new_app(walking, car)
        route_id, matrix = self.import_route(
            [("PKG-001", 2, "Rua A, 1"), ("PKG-002", 3, "Rua B, 2")], [0, 1],
        )
        plan = self.create_plan(route_id, matrix["id"]).json()
        self.assertEqual(plan["macro_stop_count"], 2)
        response = self.create_order(route_id, plan["id"], -1, 2)
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        # As duas ordens somam 7 m; a primeira gasta 3 s e a segunda 12 s.
        self.assertEqual(self.sequence_offsets(data, route_id, -1, 2), [-1, 0, 1, 2])
        self.assertEqual(data["total_distance_m"], 7)
        self.assertEqual(data["total_duration_s"], 3)

    def test_canonical_sheet_order_breaks_full_tie_and_ignores_address(self):
        car = ScriptedCarNetwork(values([-1, 0, 1, 2], distance=1.0, duration=1.0))
        walking = foot_network([0, 1])
        self.new_app(walking, car)
        # A planilha lista "Rua Z" antes de "Rua A": a ordem canônica é a da
        # planilha, nunca a alfabética dos endereços.
        route_id, matrix = self.import_route(
            [("PKG-001", 2, "Rua Z, 1"), ("PKG-002", 3, "Rua A, 2")], [0, 1],
        )
        plan = self.create_plan(route_id, matrix["id"]).json()
        first = self.create_order(route_id, plan["id"], -1, 2).json()
        second = self.create_order(route_id, plan["id"], -1, 2).json()
        self.assertEqual(self.sequence_offsets(first, route_id, -1, 2), [-1, 0, 1, 2])
        self.assertEqual(first["content_hash"], second["content_hash"])
        self.assertEqual(first["legs"], second["legs"])

    def test_single_base_order(self):
        car = ScriptedCarNetwork(values([-1, 0, 2], distance=100.0))
        car.values[(-1, 0)] = (2, 4)
        car.values[(0, 2)] = (3, 6)
        walking = ScriptedNetwork({(0, 0): 0})
        self.new_app(walking, car)
        route_id, matrix = self.import_route([("PKG-001", 1, "Rua Única, 1")], [0])
        plan = self.create_plan(route_id, matrix["id"]).json()
        response = self.create_order(route_id, plan["id"], -1, 2)
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["base_count"], 1)
        self.assertEqual(data["total_distance_m"], 5)
        self.assertEqual(data["total_duration_s"], 10)
        self.assertEqual(len(data["legs"]), 2)
        self.assertEqual(self.sequence_offsets(data, route_id, -1, 2), [-1, 0, 2])

    def test_unreachable_required_pair_is_refused(self):
        car = ScriptedCarNetwork(values([-1, 0, 2], distance=5.0))
        walking = ScriptedNetwork({(0, 0): 0})
        self.new_app(walking, car)
        route_id, matrix = self.import_route([("PKG-001", 1, "Rua Única, 1")], [0])
        plan = self.create_plan(route_id, matrix["id"]).json()
        offsets = self.offsets(route_id)
        base = delivery_node_id(next(iter(offsets)))
        # A matriz é criada no primeiro pedido e depois editada para tornar
        # obrigatório um par inacessível.
        created = self.create_vehicle_matrix(route_id, -1, 2).json()
        with self.app.state.engine.begin() as connection:
            connection.execute(text(
                "UPDATE vehicle_matrix_entries SET reachable = 0, distance_m = NULL, "
                "duration_s = NULL, error_code = 'NO_ROUTE' "
                "WHERE matrix_id = :matrix AND origin_node_id = :origin "
                "AND destination_node_id = :destination"
            ), {"matrix": created["id"], "origin": base, "destination": DESTINATION_NODE_ID})
        response = self.create_order(route_id, plan["id"], -1, 2, matrix_id=created["id"])
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("inacessível", response.json()["detail"].lower())

    def test_order_avoids_an_unreachable_pair_when_an_alternative_exists(self):
        car = ScriptedCarNetwork(values([-1, 0, 1, 2, 3], distance=1.0))
        walking = foot_network([0, 1, 2])
        self.new_app(walking, car)
        route_id, matrix = self.import_route(
            [("PKG-001", 1, "Rua A, 1"), ("PKG-002", 2, "Rua B, 2"), ("PKG-003", 3, "Rua C, 3")],
            [0, 1, 2],
        )
        plan = self.create_plan(route_id, matrix["id"]).json()
        created = self.create_vehicle_matrix(route_id, -1, 3).json()
        offsets = self.offsets(route_id)
        ids = {offset: point_id for point_id, offset in offsets.items()}
        with self.app.state.engine.begin() as connection:
            connection.execute(text(
                "UPDATE vehicle_matrix_entries SET reachable = 0, distance_m = NULL, "
                "duration_s = NULL, error_code = 'NO_ROUTE' "
                "WHERE matrix_id = :matrix AND origin_node_id = :origin "
                "AND destination_node_id = :destination"
            ), {"matrix": created["id"], "origin": delivery_node_id(ids[0]),
                "destination": delivery_node_id(ids[1])})
        response = self.create_order(route_id, plan["id"], -1, 3, matrix_id=created["id"])
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        used = {
            (leg["origin_node_id"], leg["destination_node_id"]) for leg in data["legs"]
        }
        self.assertNotIn((delivery_node_id(ids[0]), delivery_node_id(ids[1])), used)
        sequence = self.sequence_offsets(data, route_id, -1, 3)
        self.assertEqual(sorted(sequence[1:-1]), [0, 1, 2])

    def test_each_base_is_visited_once_without_duplication(self):
        car = ScriptedCarNetwork(values([-1, 0, 1, 2, 3, 4], distance=2.0))
        walking = foot_network([0, 1, 2, 3])
        self.new_app(walking, car)
        route_id, matrix = self.import_route(
            [("PKG-001", 1, "Rua A, 1"), ("PKG-002", 2, "Rua B, 2"),
             ("PKG-003", 3, "Rua C, 3"), ("PKG-004", 4, "Rua D, 4")],
            [0, 1, 2, 3],
        )
        plan = self.create_plan(route_id, matrix["id"]).json()
        self.assertEqual(plan["macro_stop_count"], 4)
        data = self.create_order(route_id, plan["id"], -1, 4).json()
        bases = [step["node_id"] for step in data["order"] if step["node_role"] == "candidate_base"]
        self.assertEqual(len(bases), 4)
        self.assertEqual(len(set(bases)), 4)
        expected = {delivery_node_id(point_id) for point_id in self.offsets(route_id)}
        self.assertEqual(set(bases), expected)
        self.assertEqual(data["order"][0]["node_role"], "origin")
        self.assertEqual(data["order"][-1]["node_role"], "destination")
        self.assertEqual(len(data["legs"]), len(bases) + 1)
        self.assertEqual(data["base_count"], 4)
        self.assertTrue(data["exact_coverage"])


class VehicleOrderSolverTests(unittest.TestCase):
    def test_exact_solver_prefers_duration_on_equal_distance(self):
        costs = {
            (ORIGIN_NODE_ID, "a"): (1.0, 1.0), (ORIGIN_NODE_ID, "b"): (1.0, 1.0),
            ("a", "b"): (1.0, 1.0), ("b", "a"): (1.0, 1.0),
            ("a", DESTINATION_NODE_ID): (5.0, 10.0), ("b", DESTINATION_NODE_ID): (5.0, 1.0),
        }
        ranks = {"a": 0, "b": 1}
        sequence, distance, duration = _solve_exact(
            ORIGIN_NODE_ID, ["a", "b"], DESTINATION_NODE_ID, costs, ranks
        )
        self.assertEqual(sequence, (ORIGIN_NODE_ID, "a", "b", DESTINATION_NODE_ID))
        self.assertEqual((distance, duration), (7.0, 3.0))

    def test_heuristic_is_deterministic_for_an_open_path(self):
        costs = {("o", "a"): (1.0, 1.0), ("a", "b"): (1.0, 1.0), ("b", "d"): (1.0, 1.0),
                 ("o", "b"): (9.0, 9.0)}
        ranks = {"a": 0, "b": 1}
        first = _solve_heuristic("o", ["a", "b"], "d", costs, ranks)
        second = _solve_heuristic("o", ["a", "b"], "d", costs, ranks)
        self.assertEqual(first, second)
        self.assertEqual(first[0], ("o", "a", "b", "d"))
        self.assertEqual(_path_cost(first[0], costs), (3.0, 3.0))


class VehicleOrderGateTests(VehicleOrderTestBase):
    def _three_base_route(self, *, confirm=True, allow_unreviewed=True):
        car = ScriptedCarNetwork(values([-1, 0, 1, 2, 3], distance=3.0))
        walking = foot_network([0, 1, 2])
        self.new_app(walking, car)
        return self.import_route(
            [("PKG-001", 1, "Rua A, 1"), ("PKG-002", 2, "Rua B, 2"), ("PKG-003", 3, "Rua C, 3")],
            [0, 1, 2], confirm=confirm, allow_unreviewed=allow_unreviewed,
        )

    def test_preview_with_pending_points_and_unverified_marking(self):
        route_id, matrix = self._three_base_route(confirm=False, allow_unreviewed=True)
        plan = self.create_plan(
            route_id, matrix["id"], planning_mode="coordinate_preview"
        ).json()
        self.assertTrue(plan["provisional_draft"])
        response = self.create_order(route_id, plan["id"], -1, 3)
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertTrue(data["provisional_draft"])
        self.assertTrue(data["draft"])
        self.assertFalse(data["stale"])
        self.assertEqual(data["base_status"], "unverified")
        self.assertFalse(data["geometry_available"])
        self.assertFalse(data["maneuvers_available"])
        self.assertFalse(data["voice_available"])
        self.assertIn("GPS", data["gps_notice"])
        self.assertIn("não uma vaga", data["parking_notice"])
        self.assertIn("Nenhuma economia", data["capability_notice"])
        self.assertIn("não homologado", data["draft_notice"])
        self.assertEqual(data["planning_mode"], "coordinate_preview")
        points = self.client.get(f"/api/v1/routes/{route_id}/delivery-points").json()
        self.assertTrue(all(point["review_status"] == "pending" for point in points))

    def test_stale_plan_after_review_is_refused(self):
        route_id, matrix = self._three_base_route(confirm=False, allow_unreviewed=True)
        plan = self.create_plan(
            route_id, matrix["id"], planning_mode="coordinate_preview"
        ).json()
        point = self.client.get(f"/api/v1/routes/{route_id}/delivery-points").json()[0]
        corrected = self.client.patch(f"/api/v1/delivery-points/{point['id']}/review", json={
            "review_status": "corrected", "expected_revision": point["revision"],
            "latitude": point["effective_latitude"] + 0.0001,
            "longitude": point["effective_longitude"],
        })
        self.assertEqual(corrected.status_code, 200, corrected.text)
        self.assertTrue(self.client.get(f"/api/v1/macro-plans/{plan['id']}").json()["stale"])
        response = self.create_order(route_id, plan["id"], -1, 3)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("desatualizada", response.json()["detail"])

    def test_missing_vehicle_provider_is_refused_without_fabricating(self):
        car = ScriptedCarNetwork(values([-1, 0, 1, 2, 3], distance=3.0))
        walking = foot_network([0, 1, 2])
        self.new_app(walking, car)
        route_id, matrix = self.import_route(
            [("PKG-001", 1, "Rua A, 1"), ("PKG-002", 2, "Rua B, 2"), ("PKG-003", 3, "Rua C, 3")],
            [0, 1, 2],
        )
        plan = self.create_plan(route_id, matrix["id"]).json()
        self.app.state.vehicle_provider = None
        response = self.create_order(route_id, plan["id"], -1, 3)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("não substituem a via", response.json()["detail"])
        with self.app.state.engine.connect() as connection:
            count = connection.execute(text("SELECT COUNT(*) FROM vehicle_matrices")).scalar()
        self.assertEqual(count, 0)

    def test_pedestrian_profile_provider_is_refused(self):
        car = ScriptedCarNetwork(values([-1, 0, 1, 2, 3], distance=3.0))
        car.profile = "foot"
        walking = foot_network([0, 1, 2])
        self.new_app(walking, car)
        route_id, matrix = self.import_route(
            [("PKG-001", 1, "Rua A, 1"), ("PKG-002", 2, "Rua B, 2"), ("PKG-003", 3, "Rua C, 3")],
            [0, 1, 2],
        )
        plan = self.create_plan(route_id, matrix["id"]).json()
        response = self.create_order(route_id, plan["id"], -1, 3)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("pedestre", response.json()["detail"])

    def test_estimate_only_incomplete_and_stale_matrices_are_refused(self):
        route_id, matrix = self._three_base_route()
        plan = self.create_plan(route_id, matrix["id"]).json()
        created = self.create_vehicle_matrix(route_id, -1, 3).json()

        with self.app.state.engine.begin() as connection:
            connection.execute(text("UPDATE vehicle_matrices SET quality = 'estimate_only' WHERE id = :id"),
                               {"id": created["id"]})
        estimate = self.create_order(route_id, plan["id"], -1, 3, matrix_id=created["id"])
        self.assertEqual(estimate.status_code, 409, estimate.text)
        self.assertIn("não é de rede", estimate.json()["detail"])

        with self.app.state.engine.begin() as connection:
            connection.execute(text("UPDATE vehicle_matrices SET quality = 'network' WHERE id = :id"),
                               {"id": created["id"]})
            connection.execute(text(
                "DELETE FROM vehicle_matrix_entries WHERE id = "
                "(SELECT MIN(id) FROM vehicle_matrix_entries WHERE matrix_id = :id)"
            ), {"id": created["id"]})
        incomplete = self.create_order(route_id, plan["id"], -1, 3, matrix_id=created["id"])
        self.assertEqual(incomplete.status_code, 409, incomplete.text)
        self.assertIn("não cobre todos os pares", incomplete.json()["detail"])

    def test_changed_dataset_revision_makes_the_vehicle_matrix_stale(self):
        route_id, matrix = self._three_base_route()
        plan = self.create_plan(route_id, matrix["id"]).json()
        created = self.create_vehicle_matrix(route_id, -1, 3).json()
        self.app.state.vehicle_provider.dataset_revision = "synthetic-car-v2"
        response = self.create_order(route_id, plan["id"], -1, 3, matrix_id=created["id"])
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("desatualizada", response.json()["detail"])

    def test_unknown_vehicle_matrix_is_refused(self):
        route_id, matrix = self._three_base_route()
        plan = self.create_plan(route_id, matrix["id"]).json()
        response = self.create_order(route_id, plan["id"], -1, 3, matrix_id="nao-existe")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("não encontrada", response.json()["detail"])

    def test_request_endpoints_must_match_the_vehicle_matrix_snapshot(self):
        route_id, matrix = self._three_base_route()
        plan = self.create_plan(route_id, matrix["id"]).json()
        created = self.create_vehicle_matrix(route_id, -1, 3).json()

        # A matriz foi calculada para a partida -1; pedir outra partida deve recusar.
        origin_mismatch = self.create_order(
            route_id, plan["id"], 0, 3, matrix_id=created["id"]
        )
        self.assertEqual(origin_mismatch.status_code, 409, origin_mismatch.text)
        self.assertIn("partida", origin_mismatch.json()["detail"])

        # A matriz foi calculada para a chegada 3; pedir outra chegada deve recusar.
        destination_mismatch = self.create_order(
            route_id, plan["id"], -1, 2, matrix_id=created["id"]
        )
        self.assertEqual(destination_mismatch.status_code, 409, destination_mismatch.text)
        self.assertIn("chegada", destination_mismatch.json()["detail"])

    def test_changed_labels_with_identical_coordinates_are_allowed(self):
        route_id, matrix = self._three_base_route()
        plan = self.create_plan(route_id, matrix["id"]).json()
        # A matriz foi gravada com os rótulos padrão; rótulos novos não entram no custo.
        created = self.create_vehicle_matrix(route_id, -1, 3).json()
        response = self.create_order(
            route_id, plan["id"], -1, 3, matrix_id=created["id"],
            labels=("Portão novo", "Destino novo"),
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["vehicle_matrix_id"], created["id"])
        self.assertEqual(data["origin"]["label"], "Portão novo")
        self.assertEqual(data["destination"]["label"], "Destino novo")
        self.assertEqual(data["stale"], False)

    def test_vehicle_matrix_snapshot_must_reference_the_expected_nodes(self):
        route_id, matrix = self._three_base_route()
        plan = self.create_plan(route_id, matrix["id"]).json()
        created = self.create_vehicle_matrix(route_id, -1, 3).json()
        snapshot = created["input_snapshot"]
        snapshot["points"][0]["node_id"] = "delivery:outra-rota"
        with self.app.state.engine.begin() as connection:
            connection.execute(text(
                "UPDATE vehicle_matrices SET input_snapshot = :snapshot WHERE id = :id"
            ), {"snapshot": json.dumps(snapshot), "id": created["id"]})
        response = self.create_order(route_id, plan["id"], -1, 3, matrix_id=created["id"])
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("nó de entrega", response.json()["detail"])

    def test_provider_failure_returns_502_without_a_matrix(self):
        car = FailingCarNetwork(values([-1, 0, 1, 2, 3], distance=3.0))
        walking = foot_network([0, 1, 2])
        self.new_app(walking, car)
        route_id, matrix = self.import_route(
            [("PKG-001", 1, "Rua A, 1"), ("PKG-002", 2, "Rua B, 2"), ("PKG-003", 3, "Rua C, 3")],
            [0, 1, 2],
        )
        plan = self.create_plan(route_id, matrix["id"]).json()
        response = self.create_order(route_id, plan["id"], -1, 3)
        self.assertEqual(response.status_code, 502, response.text)
        with self.app.state.engine.connect() as connection:
            count = connection.execute(text("SELECT COUNT(*) FROM vehicle_matrices")).scalar()
        self.assertEqual(count, 0)

    def test_matrix_and_plan_from_another_route_are_refused(self):
        route_id, matrix = self._three_base_route()
        plan = self.create_plan(route_id, matrix["id"]).json()
        # Outra rota no mesmo app, com coordenadas equivalentes e endereços novos.
        other_route_id, other_matrix = self.import_route(
            [("PKG-101", 1, "Rua Outra, 9"), ("PKG-102", 2, "Rua Alheia, 8"),
             ("PKG-103", 3, "Rua Distante, 7")],
            [0, 1, 2],
        )
        other_plan = self.create_plan(other_route_id, other_matrix["id"]).json()
        other_vehicle = self.create_vehicle_matrix(other_route_id, -1, 3).json()
        cross_matrix = self.create_order(
            route_id, plan["id"], -1, 3, matrix_id=other_vehicle["id"]
        )
        self.assertEqual(cross_matrix.status_code, 409, cross_matrix.text)
        self.assertIn("outra rota", cross_matrix.json()["detail"])
        cross_plan = self.create_order(
            route_id, other_plan["id"], -1, 3
        )
        self.assertEqual(cross_plan.status_code, 409, cross_plan.text)
        self.assertIn("proposta pertence a outra rota", cross_plan.json()["detail"])

    def test_unknown_plan_and_route_return_404(self):
        route_id, matrix = self._three_base_route()
        response = self.create_order(route_id, "nao-existe", -1, 3)
        self.assertEqual(response.status_code, 404, response.text)
        response = self.client.post(
            "/api/v1/routes/nao-existe/vehicle-orders",
            json=self.order_body("nao-existe", -1, 3),
        )
        self.assertEqual(response.status_code, 404, response.text)


class VehicleOrderHeuristicTests(VehicleOrderTestBase):
    def test_above_exact_limit_uses_a_marked_non_optimal_method(self):
        count = EXACT_BASE_LIMIT + 1
        indices = list(range(count))
        car = ScriptedCarNetwork(values([-1, *indices, 99], distance=10.0))
        walking = foot_network(indices)
        self.new_app(walking, car)
        packages = [(f"PKG-{index:03d}", index + 1, f"Rua {index}, {index}") for index in indices]
        route_id, matrix = self.import_route(packages, indices)
        plan = self.create_plan(route_id, matrix["id"], max_packages=count).json()
        self.assertEqual(plan["macro_stop_count"], count)
        response = self.create_order(route_id, plan["id"], -1, 99)
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["base_count"], count)
        self.assertFalse(data["optimal"])
        self.assertEqual(data["solution_method"], "heuristic_nearest_neighbor_2opt")
        self.assertEqual(data["exact_base_limit"], EXACT_BASE_LIMIT)
        self.assertEqual(data["total_distance_m"], 10.0 * (count + 1))
        second = self.create_order(route_id, plan["id"], -1, 99).json()
        self.assertEqual(data["content_hash"], second["content_hash"])


class VehicleOrderSurfaceTests(VehicleOrderTestBase):
    def test_panel_and_openapi_expose_the_vehicle_order(self):
        car = ScriptedCarNetwork(values([-1, 0, 1, 2, 3], distance=3.0))
        walking = foot_network([0, 1, 2])
        self.new_app(walking, car)
        route_id, matrix = self.import_route(
            [("PKG-001", 1, "Rua A, 1"), ("PKG-002", 2, "Rua B, 2"), ("PKG-003", 3, "Rua C, 3")],
            [0, 1, 2],
        )
        plan = self.create_plan(route_id, matrix["id"]).json()
        created = self.create_vehicle_matrix(route_id, -1, 3)
        self.assertEqual(created.status_code, 201, created.text)
        body = created.json()
        self.assertEqual(body["profile"], "car")
        self.assertEqual(body["quality"], "network")
        self.assertEqual(body["dataset_revision"], "synthetic-car-v1")
        self.assertFalse(body["stale"])
        self.assertEqual(body["reachable_pairs"], body["point_count"] ** 2)
        repeated = self.create_vehicle_matrix(route_id, -1, 3)
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(repeated.json()["id"], body["id"])
        self.assertTrue(repeated.json()["idempotent"])
        entries = self.client.get(
            f"/api/v1/vehicle-matrices/{body['id']}/entries?limit=10000"
        ).json()
        self.assertEqual(len(entries), body["point_count"] ** 2)
        listed = self.client.get(f"/api/v1/routes/{route_id}/vehicle-matrices").json()
        self.assertEqual([matrix["id"] for matrix in listed], [body["id"]])

        response = self.create_order(route_id, plan["id"], -1, 3)
        self.assertEqual(response.status_code, 200, response.text)

        console = self.client.get("/")
        self.assertEqual(console.status_code, 200)
        self.assertIn("ordem veicular", console.text.lower())
        script = self.client.get("/static/review.js")
        self.assertIn("renderVehicleOrder", script.text)
        self.assertIn("/vehicle-orders", script.text)
        schema = self.client.get("/openapi.json").json()
        self.assertIn("/api/v1/routes/{route_id}/vehicle-orders", schema["paths"])
        self.assertIn("/api/v1/routes/{route_id}/vehicle-matrices", schema["paths"])
        order = schema["components"]["schemas"]["VehicleOrderResponse"]["properties"]
        for field in ("order", "legs", "total_distance_m", "total_duration_s", "solution_method",
                      "optimal", "base_status", "parking_notice", "gps_notice",
                      "capability_notice", "provisional_draft", "vehicle_matrix_id",
                      "matrix_profile", "matrix_dataset_revision", "content_hash", "draft"):
            self.assertIn(field, order)
        leg = schema["components"]["schemas"]["VehicleOrderLegResponse"]["properties"]
        for field in ("origin_node_id", "destination_node_id", "origin_role",
                      "destination_role", "distance_m", "duration_s", "position"):
            self.assertIn(field, leg)
        config = self.client.get("/api/v1/maps/config").json()
        self.assertTrue(config["vehicle"]["configured"])
        self.assertEqual(config["vehicle"]["profile"], "car")
        self.assertEqual(config["vehicle"]["quality"], "network")
        self.assertEqual(config["vehicle"]["dataset_revision"], "synthetic-car-v1")
        self.assertIsNone(config["vehicle_notice"])

    def test_maps_config_reports_a_missing_vehicle_provider(self):
        car = ScriptedCarNetwork(values([-1, 0, 1, 2, 3], distance=3.0))
        walking = foot_network([0, 1, 2])
        self.new_app(walking, car)
        self.app.state.vehicle_provider = None
        config = self.client.get("/api/v1/maps/config").json()
        self.assertFalse(config["vehicle"]["configured"])
        self.assertIn("não substituem a via", config["vehicle_notice"])


class VehicleOrderServiceGuardTests(unittest.TestCase):
    def test_exact_limit_notice_matches_the_constant(self):
        from jet_rapido.vehicle_service import EXACT_NOT_FOUND_NOTICE, HEURISTIC_NOTICE
        self.assertIn(str(EXACT_BASE_LIMIT), HEURISTIC_NOTICE)
        self.assertIn("sem atravessar par inacessível", EXACT_NOT_FOUND_NOTICE)

    def test_path_cost_is_none_for_an_unreachable_leg(self):
        costs = {("a", "b"): None}
        self.assertIsNone(_path_cost(("a", "b"), costs))

    def test_vehicle_order_error_is_a_value_error(self):
        self.assertTrue(issubclass(VehicleOrderError, ValueError))


if __name__ == "__main__":
    unittest.main()

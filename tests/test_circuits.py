"""Circuitos pedestres fechados: rede e planilhas sintéticas versionadas."""

from pathlib import Path
import tempfile
import unittest
from itertools import permutations

from fastapi.testclient import TestClient
from sqlalchemy import text

from jet_rapido.api import create_app
from jet_rapido.circuit_service import (
    EXACT_POINT_LIMIT, CircuitError, _sequence_cost, _solve_heuristic,
)
from jet_rapido.config import Settings
from jet_rapido.maps import MatrixCell, MatrixComputation

from test_api import migrate
from test_importer import fixture, row


def full_matrix(indices, cost):
    return {(origin, destination): float(cost(origin, destination))
            for origin in indices for destination in indices}


class ScriptedNetwork:
    """Rede sintética dirigida: custos indexados pelo deslocamento da coordenada."""

    name = "scripted_foot"
    profile = "foot"
    quality = "network"
    cache_key = "scripted_foot:v1"

    def __init__(self, distances, *, duration_factor=2.0, unreachable=()):
        self.distances = dict(distances)
        self.duration_factor = duration_factor
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
                distance = self.distances[key]
                cells.append(MatrixCell(
                    origin_id=origin.id, destination_id=destination.id,
                    distance_m=distance, duration_s=distance * self.duration_factor,
                    reachable=True, error_code=None,
                ))
        return MatrixComputation(provider=self.name, profile=self.profile, quality=self.quality,
                                 cells=tuple(cells), dataset_version="scripted-v1")


class CircuitTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.counter = 0
        self.app = None
        self.client = None

    def import_route(self, packages, offsets, *, network=None, confirm=True,
                     allow_unreviewed=True, compute_matrix=True):
        self.counter += 1
        if network is not None:
            database_url = f"sqlite:///{(self.root / f'db-{self.counter}.db').as_posix()}"
            migrate(database_url)
            self.app = create_app(Settings(database_url=database_url), walking_provider=network)
            self.addCleanup(self.app.state.engine.dispose)
            self.client = TestClient(self.app)
            self.addCleanup(self.client.close)
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
                   "max_pairwise_m": 10_000, "max_base_roundtrip_m": 10_000}
        command.update(changes)
        return self.client.post(f"/api/v1/routes/{route_id}/macro-plans", json=command)

    def offsets(self, route_id):
        points = self.client.get(f"/api/v1/routes/{route_id}/delivery-points").json()
        return {point["id"]: round((point["effective_latitude"] + 23.5) * 1000)
                for point in points}

    def circuits(self, plan_id):
        return self.client.get(f"/api/v1/macro-plans/{plan_id}/circuits")

    def circuit_offsets(self, circuit, offsets):
        return [offsets[point_id] for point_id in circuit["sequence_point_ids"]]


class DirectedCircuitTests(CircuitTestBase):
    def test_minimal_directed_circuit_is_not_the_trivial_order(self):
        network = ScriptedNetwork({
            (0, 0): 0, (1, 1): 0, (2, 2): 0,
            (0, 1): 10, (1, 0): 1,
            (0, 2): 1, (2, 0): 30,
            (1, 2): 1, (2, 1): 30,
        })
        route_id, matrix = self.import_route(
            [("PKG-001", 1, "Rua A, 1"), ("PKG-002", 2, "Rua B, 2"), ("PKG-003", 3, "Rua C, 3")],
            [0, 1, 2], network=network,
        )
        plan = self.create_plan(route_id, matrix["id"]).json()
        self.assertEqual(plan["macro_stop_count"], 1)
        response = self.circuits(plan["id"])
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        circuit = data["circuits"][0]
        offsets = self.offsets(route_id)
        # A base A (ordem canônica) fecha em A->C->B->A (1+30+1=32), não em A->B->C->A (41).
        self.assertEqual(self.circuit_offsets(circuit, offsets), [0, 2, 1])
        self.assertEqual(circuit["candidate_base_point_id"], circuit["sequence_point_ids"][0])
        self.assertEqual(circuit["distance_m"], 32)
        self.assertEqual(circuit["duration_s"], 64)
        self.assertTrue(circuit["optimal"])
        self.assertEqual(circuit["solution_method"], "exact")
        self.assertTrue(circuit["closed"])
        self.assertEqual(circuit["point_count"], 3)
        self.assertEqual(data["total_distance_m"], 32)
        self.assertEqual(data["total_duration_s"], 64)
        # 32 m não supera o limite de ida e volta usado neste teste (10_000 m).
        self.assertEqual(data["max_base_roundtrip_m"], 10_000)
        self.assertEqual(data["circuits_exceeding_base_roundtrip"], 0)
        self.assertFalse(circuit["exceeds_base_roundtrip_limit"])
        self.assertIsNone(circuit["roundtrip_warning"])
        self.assertIn("não limita a distância total", data["base_roundtrip_limit_notice"])

    def test_circuit_above_base_roundtrip_parameter_is_warned_but_not_blocked(self):
        # Cada ida e volta individual cabe em 31 m, mas a volta completa soma 32 m.
        network = ScriptedNetwork({
            (0, 0): 0, (1, 1): 0, (2, 2): 0,
            (0, 1): 10, (1, 0): 1,
            (0, 2): 1, (2, 0): 30,
            (1, 2): 1, (2, 1): 30,
        })
        route_id, matrix = self.import_route(
            [("PKG-001", 1, "Rua A, 1"), ("PKG-002", 2, "Rua B, 2"), ("PKG-003", 3, "Rua C, 3")],
            [0, 1, 2], network=network,
        )
        plan = self.create_plan(route_id, matrix["id"], max_base_roundtrip_m=31).json()
        # O agrupamento não é alterado pelo parâmetro: continua uma macro-parada com 3 pontos.
        self.assertEqual(plan["macro_stop_count"], 1)
        self.assertEqual(plan["stops"][0]["max_base_roundtrip_m"], 31)
        response = self.circuits(plan["id"])
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        circuit = data["circuits"][0]
        self.assertEqual(circuit["distance_m"], 32)
        self.assertEqual(data["max_base_roundtrip_m"], 31)
        self.assertEqual(data["circuits_exceeding_base_roundtrip"], 1)
        self.assertTrue(circuit["exceeds_base_roundtrip_limit"])
        self.assertEqual(circuit["max_base_roundtrip_m"], 31)
        self.assertIn("não a volta completa", circuit["roundtrip_warning"])
        self.assertIn("31.0 m", circuit["roundtrip_warning"])
        self.assertIn("não limita", data["base_roundtrip_limit_notice"])
        self.assertEqual(data["point_count"], 3)
        self.assertEqual(len(circuit["sequence_point_ids"]), 3)

    def test_deterministic_tie_ignores_address_and_text_order(self):
        indices = [0, 1, 2, 3]
        # Todos os pares valem 1: a ordem ótima empata e cai no desempate canônico.
        network = ScriptedNetwork(full_matrix(indices, lambda a, b: 0 if a == b else 1))
        route_id, matrix = self.import_route(
            # Endereços em ordem alfabética inversa à ordem da planilha.
            [("PKG-001", 1, "Rua Z, 4"), ("PKG-002", 2, "Rua Y, 3"),
             ("PKG-003", 3, "Rua X, 2"), ("PKG-004", 4, "Rua W, 1")],
            indices, network=network,
        )
        plan = self.create_plan(route_id, matrix["id"]).json()
        first = self.circuits(plan["id"]).json()
        second = self.circuits(plan["id"]).json()
        offsets = self.offsets(route_id)
        # A sequência segue a ordem da planilha (0,1,2,3), nunca a ordem alfabética (3,2,1,0).
        self.assertEqual(self.circuit_offsets(first["circuits"][0], offsets), [0, 1, 2, 3])
        self.assertEqual(first["content_hash"], second["content_hash"])
        self.assertEqual(first["circuits"], second["circuits"])

    def test_single_point_circuit_is_trivial(self):
        network = ScriptedNetwork({(0, 0): 0})
        route_id, matrix = self.import_route(
            [("PKG-001", 1, "Rua Única, 1")], [0], network=network,
        )
        plan = self.create_plan(route_id, matrix["id"]).json()
        data = self.circuits(plan["id"]).json()
        circuit = data["circuits"][0]
        self.assertEqual(circuit["point_count"], 1)
        self.assertEqual(circuit["sequence_point_ids"], [plan["stops"][0]["candidate_base_point_id"]])
        self.assertEqual(circuit["distance_m"], 0)
        self.assertEqual(circuit["duration_s"], 0)
        self.assertEqual(len(circuit["legs"]), 1)
        self.assertTrue(circuit["optimal"])

    def test_unreachable_required_pair_is_refused(self):
        network = ScriptedNetwork({(0, 0): 0, (1, 1): 0, (0, 1): 5, (1, 0): 5})
        route_id, matrix = self.import_route(
            [("PKG-001", 1, "Rua A, 1"), ("PKG-002", 2, "Rua B, 2")], [0, 1], network=network,
        )
        plan = self.create_plan(route_id, matrix["id"]).json()
        points = self.client.get(f"/api/v1/routes/{route_id}/delivery-points").json()
        base_id = plan["stops"][0]["candidate_base_point_id"]
        other_id = next(point["id"] for point in points if point["id"] != base_id)
        with self.app.state.engine.begin() as connection:
            connection.execute(text(
                "UPDATE walking_matrix_entries SET reachable = 0, distance_m = NULL, "
                "duration_s = NULL, error_code = 'NO_ROUTE' "
                "WHERE matrix_id = :matrix AND origin_delivery_point_id = :origin "
                "AND destination_delivery_point_id = :destination"
            ), {"matrix": matrix["id"], "origin": other_id, "destination": base_id})
        response = self.circuits(plan["id"])
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("inacessível", response.json()["detail"].lower())

    def test_circuit_never_uses_an_unreachable_pair_when_an_alternative_exists(self):
        network = ScriptedNetwork(full_matrix([0, 1, 2], lambda a, b: 0 if a == b else 1))
        route_id, matrix = self.import_route(
            [("PKG-001", 1, "Rua A, 1"), ("PKG-002", 2, "Rua B, 2"), ("PKG-003", 3, "Rua C, 3")],
            [0, 1, 2], network=network,
        )
        plan = self.create_plan(route_id, matrix["id"]).json()
        offsets = self.offsets(route_id)
        ids = {offset: point_id for point_id, offset in offsets.items()}
        with self.app.state.engine.begin() as connection:
            connection.execute(text(
                "UPDATE walking_matrix_entries SET reachable = 0, distance_m = NULL, "
                "duration_s = NULL, error_code = 'NO_ROUTE' "
                "WHERE matrix_id = :matrix AND origin_delivery_point_id = :origin "
                "AND destination_delivery_point_id = :destination"
            ), {"matrix": matrix["id"], "origin": ids[0], "destination": ids[1]})
        data = self.circuits(plan["id"]).json()
        circuit = data["circuits"][0]
        self.assertEqual(self.circuit_offsets(circuit, offsets), [0, 2, 1])
        used = {(offsets[leg["origin_delivery_point_id"]], offsets[leg["destination_delivery_point_id"]])
                for leg in circuit["legs"]}
        self.assertNotIn((0, 1), used)

    def test_coverage_without_duplication_across_multiple_circuits(self):
        # Dois pares próximos separados por um custo acima do limite: duas macro-paradas.
        network = ScriptedNetwork({
            (0, 0): 0, (1, 1): 0, (2, 2): 0, (3, 3): 0,
            (0, 1): 1, (1, 0): 1, (2, 3): 1, (3, 2): 1,
        })
        for a, b in ((0, 2), (2, 0), (0, 3), (3, 0), (1, 2), (2, 1), (1, 3), (3, 1)):
            network.distances[(a, b)] = 500
        route_id, matrix = self.import_route(
            [("PKG-001", 1, "Rua A, 1"), ("PKG-002", 2, "Rua B, 2"),
             ("PKG-003", 3, "Rua C, 3"), ("PKG-004", 4, "Rua D, 4")],
            [0, 1, 2, 3], network=network,
        )
        plan = self.create_plan(route_id, matrix["id"], max_pairwise_m=10).json()
        self.assertEqual(plan["macro_stop_count"], 2)
        data = self.circuits(plan["id"]).json()
        self.assertEqual(data["circuit_count"], 2)
        sequenced = [point_id for circuit in data["circuits"] for point_id in circuit["sequence_point_ids"]]
        self.assertEqual(len(sequenced), len(set(sequenced)))
        expected = {point_id for stop in plan["stops"] for point_id in stop["delivery_point_ids"]}
        self.assertEqual(set(sequenced), expected)
        self.assertEqual(data["point_count"], len(expected))
        for circuit in data["circuits"]:
            stop = next(stop for stop in plan["stops"] if stop["id"] == circuit["stop_id"])
            self.assertEqual(set(circuit["sequence_point_ids"]), set(stop["delivery_point_ids"]))

    def test_above_exact_limit_uses_deterministic_non_optimal_fallback(self):
        count = EXACT_POINT_LIMIT + 1
        indices = list(range(count))
        network = ScriptedNetwork(full_matrix(indices, lambda a, b: 0 if a == b else 1))
        packages = [(f"PKG-{index:03d}", index + 1, f"Rua {index}, {index}") for index in indices]
        route_id, matrix = self.import_route(packages, indices, network=network)
        plan = self.create_plan(route_id, matrix["id"], max_packages=count).json()
        first = self.circuits(plan["id"]).json()
        second = self.circuits(plan["id"]).json()
        circuit = first["circuits"][0]
        self.assertEqual(circuit["point_count"], count)
        self.assertFalse(circuit["optimal"])
        self.assertEqual(circuit["solution_method"], "heuristic_nearest_neighbor_2opt")
        self.assertEqual(first["heuristic_circuit_count"], 1)
        self.assertFalse(first["all_circuits_exact"])
        self.assertEqual(first["exact_point_limit"], EXACT_POINT_LIMIT)
        self.assertEqual(first["content_hash"], second["content_hash"])

    def test_heuristic_group_without_found_circuit_reports_method_not_impossibility(self):
        count = EXACT_POINT_LIMIT + 1
        indices = list(range(count))
        distances = full_matrix(indices, lambda a, b: 0 if a == b else 1)
        # A base prefere o ponto 9, que depois fica sem nenhuma perna de saída.
        distances[(0, count - 1)] = 0.1
        network = ScriptedNetwork(distances)
        packages = [(f"PKG-{index:03d}", index + 1, f"Rua {index}, {index}") for index in indices]
        route_id, matrix = self.import_route(packages, indices, network=network)
        plan = self.create_plan(route_id, matrix["id"]).json()
        self.assertEqual(plan["macro_stop_count"], 1)
        self.assertEqual(len(plan["stops"][0]["delivery_point_ids"]), count)
        offsets = self.offsets(route_id)
        dead_end = next(point_id for point_id, offset in offsets.items() if offset == count - 1)
        with self.app.state.engine.begin() as connection:
            connection.execute(text(
                "UPDATE walking_matrix_entries SET reachable = 0, distance_m = NULL, "
                "duration_s = NULL, error_code = 'NO_ROUTE' "
                "WHERE matrix_id = :matrix AND origin_delivery_point_id = :origin "
                "AND destination_delivery_point_id != :origin"
            ), {"matrix": matrix["id"], "origin": dead_end})
        response = self.circuits(plan["id"])
        self.assertEqual(response.status_code, 409, response.text)
        detail = response.json()["detail"]
        self.assertIn("não encontrou", detail)
        self.assertIn("não foi descartada", detail)
        self.assertNotIn("Nenhum circuito", detail)


class HeuristicSolverTests(unittest.TestCase):
    def test_two_opt_improves_the_nearest_neighbor_tour(self):
        # Instância dirigida em que o vizinho mais próximo gasta 20 e o 2-opt atinge o ótimo 18.
        distances = {
            0: {1: 6, 2: 9, 3: 1, 4: 8},
            1: {0: 7, 2: 8, 3: 6, 4: 4},
            2: {0: 4, 1: 5, 3: 8, 4: 8},
            3: {0: 2, 1: 9, 2: 3, 4: 3},
            4: {0: 7, 1: 2, 2: 6, 3: 6},
        }
        costs = {(a, b): (float(value), float(value))
                 for a, row in distances.items() for b, value in row.items()}
        for index in range(5):
            costs[(index, index)] = (0.0, 0.0)
        ranks = {index: index for index in range(5)}
        sequence, distance, duration = _solve_heuristic(0, [1, 2, 3, 4], costs, ranks)
        optimal = min(_sequence_cost((0,) + permutation, costs)[0]
                      for permutation in permutations([1, 2, 3, 4]))
        self.assertEqual(optimal, 18)
        self.assertEqual(distance, 18)
        self.assertEqual(duration, 18)
        self.assertEqual(len(sequence), 5)
        self.assertEqual(sequence[0], 0)
        # Determinístico: repetir devolve exatamente a mesma sequência.
        self.assertEqual(_solve_heuristic(0, [1, 2, 3, 4], costs, ranks), (sequence, distance, duration))

    def test_heuristic_failure_does_not_claim_impossibility(self):
        # O ponto 2 só é alcançado depois de 1, mas 1 não tem saída: a heurística trava.
        costs = {
            (0, 0): (0.0, 0.0), (1, 1): (0.0, 0.0), (2, 2): (0.0, 0.0),
            (0, 1): (1.0, 1.0), (1, 0): (1.0, 1.0),
        }
        ranks = {0: 0, 1: 1, 2: 2}
        with self.assertRaises(CircuitError) as caught:
            _solve_heuristic(0, [1, 2], costs, ranks)
        message = str(caught.exception)
        self.assertIn("não encontrou", message)
        self.assertIn("não foi descartada", message)
        self.assertNotIn("Nenhum circuito", message)
        self.assertNotIn("matematicamente", message)


class CircuitGateTests(CircuitTestBase):
    def _three_point_route(self, network, *, confirm=True, allow_unreviewed=True):
        return self.import_route(
            [("PKG-001", 1, "Rua A, 1"), ("PKG-002", 2, "Rua B, 2"), ("PKG-003", 3, "Rua C, 3")],
            [0, 1, 2], network=network, confirm=confirm, allow_unreviewed=allow_unreviewed,
        )

    def test_preview_with_pending_points_and_unverified_marking(self):
        network = ScriptedNetwork(full_matrix([0, 1, 2], lambda a, b: 0 if a == b else 3))
        route_id, matrix = self._three_point_route(network, confirm=False, allow_unreviewed=True)
        plan = self.create_plan(
            route_id, matrix["id"], planning_mode="coordinate_preview"
        ).json()
        self.assertTrue(plan["provisional_draft"])
        data = self.circuits(plan["id"]).json()
        self.assertTrue(data["provisional_draft"])
        self.assertFalse(data["stale"])
        self.assertEqual(data["base_status"], "unverified")
        self.assertFalse(data["geometry_available"])
        self.assertFalse(data["maneuvers_available"])
        self.assertFalse(data["voice_available"])
        self.assertIn("GPS", data["gps_notice"])
        self.assertIn("Nenhuma economia", data["capability_notice"])
        self.assertIn("não homologado", data["draft_notice"])
        self.assertTrue(all(circuit["base_status"] == "unverified" for circuit in data["circuits"]))
        # Nenhum status de revisão foi alterado para calcular o circuito.
        points = self.client.get(f"/api/v1/routes/{route_id}/delivery-points").json()
        self.assertTrue(all(point["review_status"] == "pending" for point in points))

    def test_stale_plan_after_review_is_refused(self):
        network = ScriptedNetwork(full_matrix([0, 1, 2], lambda a, b: 0 if a == b else 3))
        route_id, matrix = self._three_point_route(network, confirm=False, allow_unreviewed=True)
        plan = self.create_plan(
            route_id, matrix["id"], planning_mode="coordinate_preview"
        ).json()
        self.assertEqual(self.circuits(plan["id"]).status_code, 200)
        point = self.client.get(f"/api/v1/routes/{route_id}/delivery-points").json()[0]
        corrected = self.client.patch(f"/api/v1/delivery-points/{point['id']}/review", json={
            "review_status": "corrected", "expected_revision": point["revision"],
            "latitude": point["effective_latitude"] + 0.0001,
            "longitude": point["effective_longitude"],
        })
        self.assertEqual(corrected.status_code, 200, corrected.text)
        self.assertTrue(self.client.get(f"/api/v1/macro-plans/{plan['id']}").json()["stale"])
        response = self.circuits(plan["id"])
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("desatualizada", response.json()["detail"])

    def test_estimate_only_without_snapshot_and_incomplete_are_refused(self):
        network = ScriptedNetwork(full_matrix([0, 1, 2], lambda a, b: 0 if a == b else 3))
        route_id, matrix = self._three_point_route(network)
        plan = self.create_plan(route_id, matrix["id"]).json()

        with self.app.state.engine.begin() as connection:
            connection.execute(text("UPDATE walking_matrices SET quality = 'estimate_only' WHERE id = :id"),
                               {"id": matrix["id"]})
        estimate = self.circuits(plan["id"])
        self.assertEqual(estimate.status_code, 409, estimate.text)
        self.assertIn("matriz de rede", estimate.json()["detail"])

        with self.app.state.engine.begin() as connection:
            connection.execute(text("UPDATE walking_matrices SET quality = 'network' WHERE id = :id"),
                               {"id": matrix["id"]})
            connection.execute(text("DELETE FROM walking_matrix_entries WHERE id = "
                                    "(SELECT MIN(id) FROM walking_matrix_entries WHERE matrix_id = :id)"),
                               {"id": matrix["id"]})
        incomplete = self.circuits(plan["id"])
        self.assertEqual(incomplete.status_code, 409, incomplete.text)
        self.assertIn("não cobre todos os pares", incomplete.json()["detail"])

        with self.app.state.engine.begin() as connection:
            connection.execute(text("UPDATE walking_matrices SET input_snapshot = NULL WHERE id = :id"),
                               {"id": matrix["id"]})
        no_snapshot = self.circuits(plan["id"])
        self.assertEqual(no_snapshot.status_code, 409, no_snapshot.text)
        self.assertIn("snapshot", no_snapshot.json()["detail"])

    def test_route_isolation_is_preserved(self):
        network = ScriptedNetwork({(0, 0): 0, (1, 1): 0, (0, 1): 5, (1, 0): 5})
        route_id, matrix = self.import_route(
            [("PKG-001", 1, "Rua A, 1"), ("PKG-002", 2, "Rua B, 2")], [0, 1], network=network,
        )
        other_route_id, _ = self.import_route(
            [("PKG-101", 1, "Rua Outra, 9")], [7], compute_matrix=False,
        )
        plan = self.create_plan(route_id, matrix["id"]).json()
        foreign_point = self.client.get(
            f"/api/v1/routes/{other_route_id}/delivery-points"
        ).json()[0]["id"]
        with self.app.state.engine.begin() as connection:
            connection.execute(text(
                "UPDATE macro_stop_points SET delivery_point_id = :foreign "
                "WHERE plan_id = :plan AND id = (SELECT MIN(id) FROM macro_stop_points WHERE plan_id = :plan)"
            ), {"foreign": foreign_point, "plan": plan["id"]})
        response = self.circuits(plan["id"])
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("outra rota", response.json()["detail"])

    def test_unknown_plan_returns_404(self):
        self.import_route([("PKG-001", 1, "Rua A, 1")], [0],
                          network=ScriptedNetwork({(0, 0): 0}))
        self.assertEqual(self.circuits("nao-existe").status_code, 404)


class CircuitSurfaceTests(CircuitTestBase):
    def test_panel_and_openapi_expose_circuits(self):
        network = ScriptedNetwork({(0, 0): 0})
        self.import_route([("PKG-001", 1, "Rua A, 1")], [0], network=network)
        console = self.client.get("/")
        self.assertEqual(console.status_code, 200)
        self.assertIn("circuito", console.text)
        script = self.client.get("/static/review.js")
        self.assertIn("renderCircuits", script.text)
        self.assertIn("/circuits", script.text)
        schema = self.client.get("/openapi.json").json()
        self.assertIn("/api/v1/macro-plans/{plan_id}/circuits", schema["paths"])
        circuits = schema["components"]["schemas"]["MacroPlanCircuitsResponse"]["properties"]
        for field in ("gps_notice", "base_status", "stale", "exact_point_limit",
                      "max_base_roundtrip_m", "base_roundtrip_limit_notice",
                      "circuits_exceeding_base_roundtrip",
                      "total_distance_m", "total_duration_s", "content_hash"):
            self.assertIn(field, circuits)
        stop_circuit = schema["components"]["schemas"]["MacroStopCircuitResponse"]["properties"]
        for field in ("solution_method", "optimal", "sequence_point_ids", "legs", "closed",
                      "max_base_roundtrip_m", "exceeds_base_roundtrip_limit", "roundtrip_warning"):
            self.assertIn(field, stop_circuit)
        leg = schema["components"]["schemas"]["CircuitLegResponse"]["properties"]
        self.assertIn("origin_delivery_point_id", leg)
        self.assertIn("duration_s", leg)


if __name__ == "__main__":
    unittest.main()

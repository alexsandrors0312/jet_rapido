"""Teste real do OSRM contra a rede sintética preparada no CI; sem mocks."""
import os
import unittest

from jet_rapido.maps import MatrixPoint, OSRMWalkingProvider


@unittest.skipUnless(os.getenv("JET_RAPIDO_TEST_OSRM_URL"), "OSRM de integração não configurado")
class OSRMLiveTests(unittest.TestCase):
    def test_footways_and_disconnected_components(self):
        provider = OSRMWalkingProvider(
            base_url=os.environ["JET_RAPIDO_TEST_OSRM_URL"], profile="foot",
            block_size=2, timeout_seconds=10, snap_radius_m=10,
            dataset_revision="synthetic-foot-v1",
        )
        result = provider.compute([
            MatrixPoint("a", .001, .0012), MatrixPoint("b", .001, .0028),
            MatrixPoint("c", .011, .0012),
        ])
        cells = {(cell.origin_id, cell.destination_id): cell for cell in result.cells}
        self.assertEqual(len(cells), 9)
        self.assertTrue(cells["a", "b"].reachable)
        self.assertGreater(cells["a", "b"].distance_m, 150)
        self.assertLess(cells["a", "b"].distance_m, 200)
        self.assertFalse(cells["a", "c"].reachable)
        self.assertIsNone(cells["a", "c"].distance_m)
        self.assertFalse(cells["c", "a"].reachable)
        self.assertEqual(cells["a", "c"].error_code, "NO_ROUTE")

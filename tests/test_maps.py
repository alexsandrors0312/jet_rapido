import unittest
from unittest.mock import patch

from jet_rapido.maps import (
    MapProviderError, MatrixPoint, OSRMWalkingProvider, StraightLineWalkingProvider,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def get(self, url, params):
        self.calls.append((url, params))
        return FakeResponse(self.payload)


class MapProviderTests(unittest.TestCase):
    def setUp(self):
        self.points = [
            MatrixPoint("a", -23.5, -46.6),
            MatrixPoint("b", -23.5005, -46.6005),
        ]

    def test_straight_line_returns_complete_estimate(self):
        result = StraightLineWalkingProvider(detour_factor=1.2, walking_speed_mps=1.0).compute(
            self.points
        )
        self.assertEqual(result.quality, "estimate_only")
        self.assertEqual(len(result.cells), 4)
        self.assertTrue(all(cell.reachable for cell in result.cells))
        self.assertEqual(result.cells[0].distance_m, 0)
        self.assertGreater(result.cells[1].distance_m, 0)
        self.assertAlmostEqual(result.cells[1].distance_m, result.cells[2].distance_m)

    def test_osrm_preserves_unreachable_pairs(self):
        payload = {
            "code": "Ok",
            "data_version": "2026-09-01",
            "distances": [[0, 120.0], [None, 0]],
            "durations": [[0, 95.0], [None, 0]],
        }
        fake_client = FakeClient(payload)
        provider = OSRMWalkingProvider(
            base_url="http://osrm.test", profile="foot", timeout_seconds=3, block_size=10
        )
        with patch("jet_rapido.maps.httpx.Client", return_value=fake_client):
            result = provider.compute(self.points)

        self.assertEqual(result.quality, "network")
        self.assertEqual(result.dataset_version, "2026-09-01")
        self.assertEqual(len(result.cells), 4)
        unreachable = [cell for cell in result.cells if not cell.reachable]
        self.assertEqual(len(unreachable), 1)
        self.assertEqual(unreachable[0].error_code, "NO_ROUTE")
        self.assertIsNone(unreachable[0].distance_m)
        self.assertIn("/table/v1/foot/", fake_client.calls[0][0])
        self.assertEqual(fake_client.calls[0][1]["annotations"], "distance,duration")

    def test_osrm_rejects_invalid_matrix_dimensions(self):
        fake_client = FakeClient({"code": "Ok", "distances": [[0]], "durations": [[0]]})
        provider = OSRMWalkingProvider(
            base_url="http://osrm.test", profile="foot", timeout_seconds=3, block_size=10
        )
        with patch("jet_rapido.maps.httpx.Client", return_value=fake_client):
            with self.assertRaisesRegex(MapProviderError, "dimensões"):
                provider.compute(self.points)


if __name__ == "__main__":
    unittest.main()

from pathlib import Path
import json
import tempfile
import unittest

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


ROOT = Path(__file__).resolve().parents[1]


class MigrationTests(unittest.TestCase):
    def test_stage_three_backfills_existing_packages(self):
        with tempfile.TemporaryDirectory() as directory:
            database_url = f"sqlite:///{(Path(directory) / 'backfill.db').as_posix()}"
            config = Config(str(ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(ROOT / "migrations"))
            config.set_main_option("sqlalchemy.url", database_url)
            command.upgrade(config, "20260919_0001")
            engine = create_engine(database_url)
            now = "2026-09-18T12:00:00+00:00"
            with engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO import_batches VALUES "
                    "(:batch, :hash, 'old.xlsx', 'Sheet1', 'A1:J2', 1, 'completed', 1, 0, :analysis, :now)"
                ), {"batch": "batch", "hash": "a" * 64, "analysis": json.dumps({}), "now": now})
                connection.execute(text(
                    "INSERT INTO routes VALUES "
                    "(:route, :batch, 'R-1', 'imported', 1, 1, NULL, :now)"
                ), {"route": "route", "batch": "batch", "now": now})
                connection.execute(text(
                    "INSERT INTO packages VALUES ("
                    ":package, :batch, :route, 'PKG-1', 2, 1, 1, 'Rua Antiga, 10', "
                    "'Centro', 'São Paulo', '01000-000', -23.5, -46.6, "
                    "'sao paulo|rua antiga', 'pending', :now)"
                ), {"package": "package", "batch": "batch", "route": "route", "now": now})
            engine.dispose()

            command.upgrade(config, "20260919_0002")
            engine = create_engine(database_url)
            with engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO walking_matrices (id, route_id, provider, profile, quality, input_hash, "
                    "point_count, reachable_pairs, unreachable_pairs, dataset_version, created_at) "
                    "VALUES ('old-matrix', 'route', 'straight_line', 'walking_estimate', "
                    "'estimate_only', :hash, 1, 1, 0, NULL, :now)"
                ), {"hash": "b" * 64, "now": now})
            engine.dispose()
            command.upgrade(config, "head")
            engine = create_engine(database_url)
            with engine.connect() as connection:
                package = connection.execute(text(
                    "SELECT delivery_point_id FROM packages WHERE id = 'package'"
                )).mappings().one()
                point = connection.execute(text(
                    "SELECT original_address, effective_latitude, review_status, revision "
                    "FROM delivery_points WHERE id = :id"
                ), {"id": package["delivery_point_id"]}).mappings().one()
                self.assertIsNone(connection.execute(text(
                    "SELECT input_snapshot FROM walking_matrices WHERE id = 'old-matrix'"
                )).scalar_one())
            engine.dispose()

        self.assertEqual(point["original_address"], "Rua Antiga, 10")
        self.assertEqual(point["effective_latitude"], -23.5)
        self.assertEqual(point["review_status"], "pending")
        self.assertEqual(point["revision"], 1)

    def test_coordinate_preview_migration_defaults_existing_plans_to_strict(self):
        with tempfile.TemporaryDirectory() as directory:
            database_url = f"sqlite:///{(Path(directory) / 'mode.db').as_posix()}"
            config = Config(str(ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(ROOT / "migrations"))
            config.set_main_option("sqlalchemy.url", database_url)
            command.upgrade(config, "20261001_0004")
            engine = create_engine(database_url)
            now = "2026-10-01T12:00:00+00:00"
            with engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO import_batches VALUES "
                    "(:batch, :hash, 'old.xlsx', 'Sheet1', 'A1:J2', 1, 'completed', 1, 0, :analysis, :now)"
                ), {"batch": "batch", "hash": "a" * 64, "analysis": json.dumps({}), "now": now})
                connection.execute(text(
                    "INSERT INTO routes VALUES (:route, :batch, 'R-1', 'imported', 1, 1, NULL, :now)"
                ), {"route": "route", "batch": "batch", "now": now})
                connection.execute(text(
                    "INSERT INTO walking_matrices (id, route_id, provider, profile, quality, input_hash, "
                    "point_count, reachable_pairs, unreachable_pairs, dataset_version, created_at) "
                    "VALUES ('matrix', 'route', 'osrm', 'foot', 'network', :hash, 1, 1, 0, NULL, :now)"
                ), {"hash": "b" * 64, "now": now})
                connection.execute(text(
                    "INSERT INTO macro_plans (id, route_id, walking_matrix_id, input_hash, max_packages, "
                    "max_pairwise_m, max_base_roundtrip_m, created_at) "
                    "VALUES ('plan', 'route', 'matrix', :hash, 8, 400, 600, :now)"
                ), {"hash": "c" * 64, "now": now})
            engine.dispose()

            command.upgrade(config, "head")
            engine = create_engine(database_url)
            with engine.connect() as connection:
                mode = connection.execute(text(
                    "SELECT planning_mode FROM macro_plans WHERE id = 'plan'"
                )).scalar_one()
            engine.dispose()

        self.assertEqual(mode, "strict")


if __name__ == "__main__":
    unittest.main()

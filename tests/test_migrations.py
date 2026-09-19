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

            command.upgrade(config, "head")
            engine = create_engine(database_url)
            with engine.connect() as connection:
                package = connection.execute(text(
                    "SELECT delivery_point_id FROM packages WHERE id = 'package'"
                )).mappings().one()
                point = connection.execute(text(
                    "SELECT original_address, effective_latitude, review_status "
                    "FROM delivery_points WHERE id = :id"
                ), {"id": package["delivery_point_id"]}).mappings().one()
            engine.dispose()

        self.assertEqual(point["original_address"], "Rua Antiga, 10")
        self.assertEqual(point["effective_latitude"], -23.5)
        self.assertEqual(point["review_status"], "pending")


if __name__ == "__main__":
    unittest.main()

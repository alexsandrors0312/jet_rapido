"""Prepara uma demonstração sintética separada do banco operacional."""
from pathlib import Path
from tempfile import TemporaryDirectory
import sys

from alembic import command
from alembic.config import Config
from openpyxl import Workbook
from fastapi.testclient import TestClient

from jet_rapido.api import create_app
from jet_rapido.config import Settings
from jet_rapido.importer import HEADERS


def main():
    root = Path(__file__).resolve().parents[1]
    url = "sqlite:///" + (root / "outputs" / "review-demo.db").as_posix()
    (root / "outputs").mkdir(exist_ok=True)
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    # O env.py prioriza DATABASE_URL. Recusar evita tocar um banco diferente da demonstração.
    import os
    if os.getenv("DATABASE_URL") and os.environ["DATABASE_URL"] != url:
        sys.exit("Remova DATABASE_URL antes de preparar a demonstração.")
    command.upgrade(config, "head")
    app = create_app(Settings(database_url=url))
    try:
        with TestClient(app) as client:
            if client.get("/api/v1/routes").json():
                print("Demonstração existente preservada.")
                return
            with TemporaryDirectory() as directory:
                path = Path(directory) / "demo.xlsx"
                book = Workbook()
                sheet = book.active
                sheet.append(HEADERS)
                for index, (address, lat, lng) in enumerate([
                    ("Rua de Demonstração, 10", -23.550, -46.630),
                    ("Rua de Demonstração, 20", -23.5504, -46.630),
                    ("Travessa de Teste, 5", -23.5505, -46.6307),
                ], 1):
                    sheet.append(["DEMO — DADOS SINTÉTICOS", index, index, f"DEMO-{index}", address,
                                  "Bairro fictício", "São Paulo", "01000-000", lat, lng])
                book.save(path)
                book.close()
                response = client.post("/api/v1/imports", files={"file": ("demo.xlsx", path.read_bytes())})
                response.raise_for_status()
                print("Demonstração preparada: 3 pacotes sintéticos, 3 entradas pendentes.")
    finally:
        app.state.engine.dispose()


if __name__ == "__main__":
    main()

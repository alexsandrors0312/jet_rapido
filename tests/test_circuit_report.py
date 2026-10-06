"""Relatório privado de circuitos: segurança da URL e conteúdo agregado."""

import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from test_circuits import CircuitTestBase, ScriptedNetwork


ROOT = Path(__file__).resolve().parents[1]


def load_report_module():
    spec = importlib.util.spec_from_file_location(
        "jet_rapido_circuit_report", ROOT / "scripts" / "circuit_report.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeEngine:
    def dispose(self):
        return None


class _EmptySession:
    def scalars(self, statement):
        return []


class _FakeSessionFactory:
    """Sessão vazia: o relatório é gerado sem tocar em banco externo."""

    def __call__(self):
        return self

    def __enter__(self):
        return _EmptySession()

    def __exit__(self, *exc_info):
        return False


class CircuitReportSecurityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.module = load_report_module()

    def test_synthetic_password_url_is_never_written_or_printed(self):
        synthetic = (
            "postgresql+psycopg://operador:senha-SUPER-secreta@db.interno.example:5432/jet_rapido"
        )
        output = self.root / "report.md"
        console = io.StringIO()
        with mock.patch.object(self.module, "create_database_engine", return_value=_FakeEngine()), \
                mock.patch.object(self.module, "create_session_factory",
                                  return_value=_FakeSessionFactory()), \
                contextlib.redirect_stdout(console):
            code = self.module.main(["--database-url", synthetic, "--output", str(output)])
        self.assertEqual(code, 0)
        text = output.read_text(encoding="utf-8")
        for leaked in (synthetic, "senha-SUPER-secreta", "db.interno.example", "postgresql"):
            self.assertNotIn(leaked, text)
            self.assertNotIn(leaked, console.getvalue())
        # O rótulo é fixo e não revela host, caminho nem credenciais.
        self.assertNotIn("Banco:", text)
        self.assertIn("URL de conexão omitida por segurança", text)


class CircuitReportContentTests(CircuitTestBase):
    def test_aggregated_report_shows_roundtrip_limit_warning_without_connection(self):
        module = load_report_module()
        network = ScriptedNetwork({
            (0, 0): 0, (1, 1): 0, (2, 2): 0,
            (0, 1): 10, (1, 0): 1,
            (0, 2): 1, (2, 0): 30,
            (1, 2): 1, (2, 1): 30,
        })
        route_id, matrix = self.import_route(
            [("PKG-001", 1, "Rua A, 1"), ("PKG-002", 2, "Rua B, 2"),
             ("PKG-003", 3, "Rua C, 3")],
            [0, 1, 2], network=network,
        )
        self.create_plan(route_id, matrix["id"], max_base_roundtrip_m=31)
        database_url = self.app.state.engine.url.render_as_string(hide_password=False)
        output = self.root / "aggregate.md"
        console = io.StringIO()
        with contextlib.redirect_stdout(console):
            code = module.main(["--database-url", database_url, "--output", str(output)])
        self.assertEqual(code, 0)
        text = output.read_text(encoding="utf-8")
        self.assertIn("31.0 m por endereço", text)
        self.assertIn("não limita a distância total", text)
        self.assertIn("Supera ida/volta", text)
        self.assertIn("sim, não limita a volta completa", text)
        self.assertIn("Aviso —", text)
        self.assertIn("Circuitos acima do limite de ida e volta à base: 1", text)
        # Nenhuma forma da URL de conexão entra no arquivo nem no console.
        self.assertNotIn(database_url, text)
        self.assertNotIn("Banco:", text)
        self.assertNotIn(database_url, console.getvalue())


if __name__ == "__main__":
    unittest.main()

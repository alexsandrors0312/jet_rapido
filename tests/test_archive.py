from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from jet_rapido.archive import validate_xlsx_archive
from jet_rapido.importer import ImportValidationError


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "archive.xlsx"

    def build(self, extra: dict[str, bytes] | None = None):
        with ZipFile(self.path, "w") as archive:
            archive.writestr("[Content_Types].xml", b"content")
            archive.writestr("xl/workbook.xml", b"workbook")
            for name, content in (extra or {}).items():
                archive.writestr(name, content)

    def test_valid_minimal_structure(self):
        self.build()
        validate_xlsx_archive(self.path, max_entries=10, max_uncompressed_bytes=100)

    def test_rejects_expanded_size(self):
        self.build({"xl/large.xml": b"x" * 100})
        with self.assertRaisesRegex(ImportValidationError, "descompactado"):
            validate_xlsx_archive(self.path, max_entries=10, max_uncompressed_bytes=50)

    def test_rejects_too_many_members(self):
        self.build({"xl/a.xml": b"a", "xl/b.xml": b"b"})
        with self.assertRaisesRegex(ImportValidationError, "internos demais"):
            validate_xlsx_archive(self.path, max_entries=3, max_uncompressed_bytes=100)

    def test_rejects_path_traversal(self):
        self.build({"../outside": b"bad"})
        with self.assertRaisesRegex(ImportValidationError, "caminho interno"):
            validate_xlsx_archive(self.path, max_entries=10, max_uncompressed_bytes=100)

    def test_rejects_duplicate_members(self):
        self.build()
        with ZipFile(self.path, "a") as archive:
            with self.assertWarns(UserWarning):
                archive.writestr("xl/workbook.xml", b"duplicate")
        with self.assertRaisesRegex(ImportValidationError, "duplicados"):
            validate_xlsx_archive(self.path, max_entries=10, max_uncompressed_bytes=100)


if __name__ == "__main__":
    unittest.main()

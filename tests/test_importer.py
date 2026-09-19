"""Fixtures OOXML mínimas e sintéticas; nenhum dado real é versionado."""
from pathlib import Path
import tempfile
import unittest
from xml.sax.saxutils import escape
from zipfile import ZipFile

from jet_rapido.importer import HEADERS, ImportValidationError, import_workbook, street_key


def fixture(path, records, headers=HEADERS, formula=False):
    rows = []
    for r, values in enumerate([headers, *records], 1):
        cells = []
        for c, value in enumerate(values):
            ref = f"{chr(65+c)}{r}"
            if formula and r == 2 and c == 4:
                cells.append(f'<c r="{ref}"><f>1+1</f><v>2</v></c>')
            elif value is not None:
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>')
        rows.append(f'<row r="{r}">{"".join(cells)}</row>')
    with ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        z.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><dimension ref="A1:A1"/><sheetData>'+"".join(rows)+'</sheetData></worksheet>')


def row(tracking="PKG-001", stop=1, address="Av. Exemplo, 10"):
    return ["ROTA-TESTE", 1, stop, tracking, address, "Bairro Teste", "São Paulo", "01234-000", -23.5, -46.6]


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "test.xlsx"

    def load(self, records, **kwargs):
        fixture(self.path, records, **kwargs)
        return import_workbook(self.path)

    def test_incorrect_dimension_does_not_drop_packages(self):
        result = self.load([row(), row("PKG-002", 2)])
        self.assertEqual(result["summary"]["packages"], 2)
        self.assertEqual(result["source"]["declared_dimension"], "A1:A1")
        self.assertEqual(result["packages"][1]["source_row"], 3)

    def test_missing_stop_preserves_package(self):
        result = self.load([row(stop="-")])
        self.assertIsNone(result["packages"][0]["original_stop"])
        self.assertEqual(result["summary"]["without_stop"], 1)

    def test_duplicate_tracking_rejected(self):
        with self.assertRaisesRegex(ImportValidationError, "duplicado"):
            self.load([row(), row()])

    def test_bad_coordinates_rejected(self):
        for value in ["nan", "inf", 91, None, "abc"]:
            with self.subTest(value=value):
                record = row()
                record[8] = value
                with self.assertRaisesRegex(ImportValidationError, "Latitude"):
                    self.load([record])

    def test_formula_rejected(self):
        with self.assertRaisesRegex(ImportValidationError, "fórmula"):
            self.load([row()], formula=True)

    def test_missing_header_rejected(self):
        with self.assertRaisesRegex(ImportValidationError, "Cabeçalhos"):
            self.load([row()], headers=[*HEADERS[:-1], "Outro"])

    def test_street_alias_detected_without_merging_packages(self):
        result = self.load([row(), row("PKG-002", 2, "Avenida Exemplo, 20")])
        self.assertEqual(result["summary"]["split_street_candidates"], 1)
        self.assertEqual(result["split_streets"][0]["original_stops"], [1, 2])
        self.assertEqual(len(result["packages"]), 2)

    def test_same_coordinates_do_not_merge_packages(self):
        result = self.load([row(), row("PKG-002")])
        self.assertEqual(result["summary"]["unique_coordinates"], 1)
        self.assertEqual(result["summary"]["packages"], 2)

    def test_empty_file_rejected(self):
        with self.assertRaisesRegex(ImportValidationError, "Nenhum pacote"):
            self.load([])

    def test_text_and_postal_code_preserved(self):
        result = self.load([row()])
        self.assertEqual(result["packages"][0]["postal_code"], "01234-000")
        self.assertEqual(result["packages"][0]["address"], "Av. Exemplo, 10")

    def test_city_part_of_street_key(self):
        self.assertNotEqual(street_key("Rua A, 1", "Cidade A"), street_key("Rua A, 1", "Cidade B"))

    def test_fractional_stop_rejected(self):
        with self.assertRaisesRegex(ImportValidationError, "inteiro"):
            self.load([row(stop=1.5)])

    def test_oversized_identifier_rejected(self):
        record = row()
        record[3] = "X" * 256
        with self.assertRaisesRegex(ImportValidationError, "excede 255"):
            self.load([record])


if __name__ == "__main__":
    unittest.main()

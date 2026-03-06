import datetime as dt
import tempfile
import unittest
import zipfile
from pathlib import Path

from modules.dna_automanage import build_excel


class TestExcelReportBuild(unittest.TestCase):
    def test_build_excel_handles_non_string_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.xlsx"
            build_excel(
                [
                    {
                        "name": "Summary",
                        "headers": ["Item", "Value"],
                        "rows": [["Job Start at", dt.datetime(2026, 3, 6, 8, 3, 43)], ["Impacted", 12]],
                        "wrap_cols": {1},
                    }
                ],
                out,
            )

            self.assertTrue(out.exists())
            with zipfile.ZipFile(out, "r") as zf:
                workbook_xml = zf.read("xl/workbook.xml").decode("utf-8")
                sheet_xml = zf.read("xl/worksheets/sheet1.xml").decode("utf-8")

            self.assertIn("<sheet name='Summary'", workbook_xml)
            self.assertIn("2026-03-06 08:03:43", sheet_xml)
            self.assertIn(">12<", sheet_xml)


if __name__ == "__main__":
    unittest.main()

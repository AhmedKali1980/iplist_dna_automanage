import tempfile
import unittest
from pathlib import Path

from modules.dna_automanage import copy_stub_csv, parse_bool


class TestStubHelpers(unittest.TestCase):
    def test_parse_bool_truthy_and_falsey(self):
        self.assertTrue(parse_bool("true"))
        self.assertTrue(parse_bool(" YES "))
        self.assertTrue(parse_bool("1"))
        self.assertFalse(parse_bool("false"))
        self.assertFalse(parse_bool("0"))
        self.assertFalse(parse_bool(""))

    def test_copy_stub_csv(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "sample.csv").write_text("a,b\n1,2\n", encoding="utf-8")
            out = root / "out.csv"

            copy_stub_csv(root, out, "sample.csv")

            self.assertEqual(out.read_text(encoding="utf-8"), "a,b\n1,2\n")


if __name__ == "__main__":
    unittest.main()

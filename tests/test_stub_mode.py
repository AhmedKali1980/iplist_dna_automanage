import logging
import tempfile
import unittest
from pathlib import Path

from modules.dna_automanage import archive_older_run_dirs, copy_stub_csv, parse_bool


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

    def test_archive_older_run_dirs_keeps_latest_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old = root / "20240101-010101"
            new = root / "20240101-020202"
            old.mkdir()
            new.mkdir()
            (old / "old.txt").write_text("old", encoding="utf-8")
            (new / "new.txt").write_text("new", encoding="utf-8")

            logger = logging.getLogger("test")
            archive_older_run_dirs(root, logger)

            self.assertTrue(new.exists())
            self.assertFalse(old.exists())
            self.assertTrue((root / "20240101-010101.tar.gz").exists())


if __name__ == "__main__":
    unittest.main()

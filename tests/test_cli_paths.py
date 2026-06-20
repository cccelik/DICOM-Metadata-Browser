import tempfile
import unittest
from pathlib import Path

from dicom_browser.cli_paths import expand_path_patterns, safe_path_name, split_inputs_and_optional_db


class CliPathTests(unittest.TestCase):
    def test_safe_path_name_normalizes_user_input(self):
        self.assertEqual(safe_path_name(" Patient Data.zip "), "Patient_Data.zip")
        self.assertEqual(safe_path_name("../"), "dicom_input")

    def test_expand_path_patterns_expands_quoted_wildcard(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "USB10").mkdir()
            (base / "USB11").mkdir()
            (base / "USB20").mkdir()

            matches = expand_path_patterns([str(base / "USB1?")])

            self.assertEqual([path.name for path in matches], ["USB10", "USB11"])

    def test_expand_path_patterns_keeps_unmatched_value(self):
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "USB1?"

            matches = expand_path_patterns([str(missing)])

            self.assertEqual(matches, [missing.resolve()])

    def test_split_inputs_and_optional_db_treats_final_db_as_database(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "USB10").mkdir()
            (base / "USB11").mkdir()

            inputs, db_path = split_inputs_and_optional_db(
                [str(base / "USB1?"), "wildcard.db"],
                explicit_db_path=None,
                default_db_path="dicom_metadata.db",
            )

            self.assertEqual([path.name for path in inputs], ["USB10", "USB11"])
            self.assertEqual(db_path, "wildcard.db")

    def test_split_inputs_and_optional_db_preserves_legacy_db_name_without_suffix(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            input_root = base / "input"
            input_root.mkdir()

            inputs, db_path = split_inputs_and_optional_db(
                [str(input_root), "my_project"],
                explicit_db_path=None,
                default_db_path="dicom_metadata.db",
            )

            self.assertEqual(inputs, [input_root.resolve()])
            self.assertEqual(db_path, "my_project")


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import extract_and_process


class ExtractAndProcessTests(unittest.TestCase):
    def test_default_output_root_uses_unique_sample_directory(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            old_root = extract_and_process.DEFAULT_SAMPLE_ROOT
            extract_and_process.DEFAULT_SAMPLE_ROOT = base
            try:
                input_path = base / "Patient Data.zip"
                input_path.write_bytes(b"x")
                first = extract_and_process._default_output_root(input_path)
                first.mkdir()
                second = extract_and_process._default_output_root(input_path)
            finally:
                extract_and_process.DEFAULT_SAMPLE_ROOT = old_root

        self.assertEqual(first.name, "Patient_Data_samples")
        self.assertEqual(second.name, "Patient_Data_samples_2")

    def test_resolve_inputs_output_and_db_accepts_positional_output_with_db(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            input_path = base / "raw"
            output_path = base / "rawFiltered"
            input_path.mkdir()

            inputs, output_root, db_path = extract_and_process._resolve_inputs_output_and_db(
                Namespace(
                    inputs=[str(input_path), str(output_path)],
                    output_root=None,
                    db_path="raw.db",
                )
            )

        self.assertEqual(inputs, [input_path.resolve()])
        self.assertEqual(output_root, output_path.resolve())
        self.assertEqual(db_path, "raw.db")


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()

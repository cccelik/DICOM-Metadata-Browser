import tempfile
import unittest
import zipfile
from pathlib import Path

import py7zr

from extract_one_per_series import extract_one_per_series


class ExtractOnePerSeriesTests(unittest.TestCase):
    def test_extract_copies_first_dicom_per_series_and_reports_progress(self):
        events = []
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            input_root = base / "input"
            output_root = base / "output"
            series_a = input_root / "patient-a" / "study-a" / "series-a"
            series_b = input_root / "patient-b" / "study-b" / "series-b"
            series_a.mkdir(parents=True)
            series_b.mkdir(parents=True)
            (series_a / "z-last.dcm").write_bytes(b"z")
            (series_a / "a-first.dcm").write_bytes(b"a")
            (series_a / "notes.txt").write_text("ignore")
            (series_b / "sample.ima").write_bytes(b"b")

            result = extract_one_per_series(input_root, output_root, progress_callback=events.append)

            self.assertEqual(result["copied"], 2)
            self.assertEqual(result["series"], 2)
            self.assertTrue((output_root / "patient-a" / "study-a" / "series-a" / "a-first.dcm").exists())
            self.assertFalse((output_root / "patient-a" / "study-a" / "series-a" / "z-last.dcm").exists())
            self.assertTrue((output_root / "patient-b" / "study-b" / "series-b" / "sample.ima").exists())
            self.assertTrue(events)
            self.assertEqual(events[0]["phase"], "Scanning")
            self.assertEqual(events[-1]["phase"], "Copying")
            self.assertTrue(events[-1]["done"])
            self.assertEqual(events[-1]["percent"], 100.0)
            self.assertIn("memory_mb", events[-1])

    def test_extract_reports_done_when_no_dicom_files_exist(self):
        events = []
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            input_root = base / "input"
            output_root = base / "output"
            input_root.mkdir()
            (input_root / "notes.txt").write_text("ignore")

            result = extract_one_per_series(input_root, output_root, progress_callback=events.append)

            self.assertEqual(result["copied"], 0)
            self.assertEqual(result["series"], 0)
            self.assertTrue(events[-1]["done"])
            self.assertEqual(events[-1]["message"], "No DICOM files found")

    def test_extract_accepts_zip_archive_input(self):
        events = []
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            archive_path = base / "input.zip"
            output_root = base / "output"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("patient-a/study-a/series-a/z-last.dcm", b"z")
                archive.writestr("patient-a/study-a/series-a/a-first.dcm", b"a")
                archive.writestr("patient-b/study-b/series-b/sample.ima", b"b")
                archive.writestr("patient-b/study-b/series-b/notes.txt", "ignore")

            result = extract_one_per_series(archive_path, output_root, progress_callback=events.append)

            self.assertEqual(result["copied"], 2)
            self.assertEqual(result["series"], 2)
            self.assertTrue((output_root / "patient-a" / "study-a" / "series-a" / "a-first.dcm").exists())
            self.assertFalse((output_root / "patient-a" / "study-a" / "series-a" / "z-last.dcm").exists())
            self.assertTrue((output_root / "patient-b" / "study-b" / "series-b" / "sample.ima").exists())
            self.assertTrue(any(event["phase"] == "Extracting" for event in events))
            self.assertTrue(any("archive entries" in event.get("message", "") for event in events))

    def test_extract_accepts_7z_archive_input(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            archive_path = base / "input.7z"
            output_root = base / "output"
            with py7zr.SevenZipFile(archive_path, "w") as archive:
                archive.writestr(b"a", "patient-a/study-a/series-a/a-first.dcm")
                archive.writestr(b"b", "patient-b/study-b/series-b/sample.ima")

            result = extract_one_per_series(archive_path, output_root)

            self.assertEqual(result["copied"], 2)
            self.assertTrue((output_root / "patient-a" / "study-a" / "series-a" / "a-first.dcm").exists())
            self.assertTrue((output_root / "patient-b" / "study-b" / "series-b" / "sample.ima").exists())

    def test_extract_rejects_non_directory_input(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            with self.assertRaises(ValueError):
                extract_one_per_series(base / "missing", base / "output")


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

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

    def test_extract_prefers_non_raw_candidate_within_series(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            input_root = base / "input"
            output_root = base / "output"
            series = input_root / "patient" / "study" / "series"
            series.mkdir(parents=True)
            raw_file = series / "a-raw.ima"
            image_file = series / "b-image.ima"
            raw_file.write_bytes(b"raw")
            image_file.write_bytes(b"image")

            with patch(
                "extract_one_per_series.has_private_bulk_data",
                side_effect=lambda path: path.name == raw_file.name,
            ):
                result = extract_one_per_series(input_root, output_root)

            self.assertEqual(result["copied"], 1)
            self.assertFalse((output_root / "patient" / "study" / "series" / raw_file.name).exists())
            self.assertTrue((output_root / "patient" / "study" / "series" / image_file.name).exists())

    def test_extract_stops_private_bulk_checks_after_first_usable_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            input_root = base / "input"
            output_root = base / "output"
            series = input_root / "patient" / "study" / "series"
            series.mkdir(parents=True)
            first_file = series / "a-image.ima"
            later_file = series / "b-image.ima"
            first_file.write_bytes(b"image")
            later_file.write_bytes(b"image")

            with patch("extract_one_per_series.has_private_bulk_data", return_value=False) as has_bulk_data:
                result = extract_one_per_series(input_root, output_root)

            self.assertEqual(result["copied"], 1)
            self.assertEqual(has_bulk_data.call_count, 1)
            self.assertEqual(has_bulk_data.call_args.args[0].resolve(), first_file.resolve())
            self.assertTrue((output_root / "patient" / "study" / "series" / first_file.name).exists())

    def test_extract_debug_callback_reports_directory_only(self):
        messages = []
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            input_root = base / "input"
            output_root = base / "output"
            series = input_root / "patient" / "study" / "series"
            series.mkdir(parents=True)
            sample_file = series / "a-image.ima"
            sample_file.write_bytes(b"image")

            with patch("extract_one_per_series.has_private_bulk_data", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    extract_one_per_series(input_root, output_root, debug_callback=messages.append)

            self.assertTrue(
                any(f"Directory 4: {series.resolve()}" in message for message in messages)
            )
            self.assertFalse(any("Checking private bulk data" in message for message in messages))
            self.assertFalse(any("Selected sample" in message for message in messages))

    def test_extract_log_callback_reports_file_before_private_bulk_check(self):
        messages = []
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            input_root = base / "input"
            output_root = base / "output"
            series = input_root / "patient" / "study" / "series"
            series.mkdir(parents=True)
            sample_file = series / "a-image.ima"
            sample_file.write_bytes(b"image")

            with patch("extract_one_per_series.has_private_bulk_data", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    extract_one_per_series(input_root, output_root, log_callback=messages.append)

            self.assertTrue(
                any(f"Checking private bulk data 1/1: {sample_file.resolve()}" in message for message in messages)
            )

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

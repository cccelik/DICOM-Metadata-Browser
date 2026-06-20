import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import py7zr
from pydicom.tag import Tag

from dicom_browser import dicom_discovery


class DicomDiscoveryTests(unittest.TestCase):
    def test_is_metadata_artifact(self):
        self.assertTrue(dicom_discovery.is_metadata_artifact(Path(".DS_Store")))
        self.assertTrue(dicom_discovery.is_metadata_artifact(Path("._hidden")))
        self.assertTrue(dicom_discovery.is_metadata_artifact(Path("__MACOSX/a/file")))
        self.assertFalse(dicom_discovery.is_metadata_artifact(Path("scan/file.dcm")))

    def test_has_dicom_signature(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            sig_file = base / "sig.bin"
            bad_file = base / "bad.bin"

            sig_file.write_bytes(b"\x00" * 128 + b"DICM" + b"\x00" * 8)
            bad_file.write_bytes(b"\x00" * 132)

            self.assertTrue(dicom_discovery.has_dicom_signature(sig_file))
            self.assertFalse(dicom_discovery.has_dicom_signature(bad_file))

    def test_is_dicom_candidate_extension_and_signature(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            ext_file = base / "image.dcm"
            sig_file = base / "nosuffix"
            txt_file = base / "note.txt"

            ext_file.write_bytes(b"not-a-real-dicom")
            sig_file.write_bytes(b"\x00" * 128 + b"DICM")
            txt_file.write_text("plain text")

            self.assertTrue(dicom_discovery.is_dicom_candidate(ext_file))
            self.assertTrue(dicom_discovery.is_dicom_candidate(sig_file))
            self.assertFalse(dicom_discovery.is_dicom_candidate(txt_file))

    def test_collect_dicom_files_recursive_and_limit(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            nested = base / "a" / "b"
            nested.mkdir(parents=True)

            (base / "one.dcm").write_bytes(b"x")
            (nested / "two.ima").write_bytes(b"y")
            (nested / "other.txt").write_text("z")

            recursive = dicom_discovery.collect_dicom_files(base, recursive=True)
            non_recursive = dicom_discovery.collect_dicom_files(base, recursive=False)
            limited = dicom_discovery.collect_dicom_files(base, recursive=True, limit=1)

            self.assertEqual(len(recursive), 2)
            self.assertEqual(len(non_recursive), 1)
            self.assertEqual(len(limited), 1)

    def test_collect_dicom_files_skips_oversized_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            small = base / "small.dcm"
            large = base / "large.dcm"
            small.write_bytes(b"x")
            large.write_bytes(b"x" * 12)

            files = dicom_discovery.collect_dicom_files(base, max_file_bytes=10)

            self.assertEqual(files, [small])

    def test_collect_dicom_files_can_include_oversized_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            large = base / "large.dcm"
            large.write_bytes(b"x" * 12)

            files = dicom_discovery.collect_dicom_files(
                base,
                max_file_bytes=10,
                include_oversized=True,
            )

            self.assertEqual(files, [large])

    def test_analyze_input_size_reports_oversized_dicom_like_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "small.dcm").write_bytes(b"x")
            (base / "large.dcm").write_bytes(b"x" * 12)
            (base / "note.txt").write_text("ignore")

            analysis = dicom_discovery.analyze_input_size(base, max_file_bytes=10)

            self.assertTrue(analysis["exists"])
            self.assertEqual(analysis["candidate_files"], 1)
            self.assertEqual(analysis["oversized_dicom_like_files"], 1)
            self.assertEqual(analysis["oversized_dicom_like_bytes"], 12)
            self.assertGreater(analysis["skipped_by_threshold_percent"], 0)

    def test_analyze_zip_size_uses_member_sizes_without_extracting(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            archive_path = base / "input.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("small.dcm", b"x")
                archive.writestr("large.dcm", b"x" * 12)

            analysis = dicom_discovery.analyze_zip_size(archive_path, max_file_bytes=10)

            self.assertTrue(analysis["exists"])
            self.assertEqual(analysis["candidate_files"], 1)
            self.assertEqual(analysis["oversized_dicom_like_files"], 1)

    def test_analyze_7z_size_uses_member_sizes_without_extracting(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            archive_path = base / "input.7z"
            with py7zr.SevenZipFile(archive_path, "w") as archive:
                archive.writestr(b"x", "small.dcm")
                archive.writestr(b"x" * 12, "large.dcm")

            analysis = dicom_discovery.analyze_7z_size(archive_path, max_file_bytes=10)

            self.assertTrue(analysis["exists"])
            self.assertEqual(analysis["candidate_files"], 1)
            self.assertEqual(analysis["oversized_dicom_like_files"], 1)

    def test_can_parse_as_dicom_handles_parser_errors(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            file_path = base / "noext"
            file_path.write_text("x")
            with patch("dicom_browser.dicom_discovery.pydicom.dcmread", side_effect=ValueError("bad")):
                self.assertFalse(dicom_discovery.can_parse_as_dicom(file_path))

    def test_is_dicom_candidate_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = base / "real.dcm"
            target.write_bytes(b"x")
            link = base / "link.dcm"
            link.symlink_to(target)
            self.assertFalse(dicom_discovery.is_dicom_candidate(link))

    def test_is_dicom_candidate_rejects_extensionless_text_file(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            license_file = base / "LICENSE"
            license_file.write_text("License\nThis is not a DICOM file.")
            self.assertFalse(dicom_discovery.is_dicom_candidate(license_file))

    def test_private_bulk_data_boundary_ignores_normal_pixel_data(self):
        self.assertTrue(
            dicom_discovery.is_private_bulk_data_boundary(Tag(0x7FE1, 0x1010), "OB", 90 * 1024 * 1024)
        )
        self.assertTrue(
            dicom_discovery.is_private_bulk_data_boundary(Tag(0x0029, 0x1010), "OB", 9 * 1024 * 1024)
        )
        self.assertFalse(
            dicom_discovery.is_private_bulk_data_boundary(Tag(0x7FE0, 0x0010), "OW", 90 * 1024 * 1024)
        )
        self.assertFalse(
            dicom_discovery.is_private_bulk_data_boundary(Tag(0x0029, 0x1010), "OB", 4096)
        )

    def test_has_private_bulk_data_reports_private_raw_before_pixel_data(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "raw.ima"
            path.write_bytes(b"\x00" * 128 + b"DICM")

            def fake_read_partial(_fh, stop_when=None, force=False):
                self.assertFalse(force)
                self.assertTrue(stop_when(Tag(0x7FE1, 0x1010), "OB", 90 * 1024 * 1024))

            with patch("dicom_browser.dicom_discovery.read_partial", side_effect=fake_read_partial):
                self.assertTrue(dicom_discovery.has_private_bulk_data(path))

    def test_has_private_bulk_data_returns_false_for_normal_pixel_data(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "image.dcm"
            path.write_bytes(b"\x00" * 128 + b"DICM")

            def fake_read_partial(_fh, stop_when=None, force=False):
                self.assertFalse(force)
                self.assertTrue(stop_when(Tag(0x7FE0, 0x0010), "OW", 90 * 1024 * 1024))

            with patch("dicom_browser.dicom_discovery.read_partial", side_effect=fake_read_partial):
                self.assertFalse(dicom_discovery.has_private_bulk_data(path))


if __name__ == "__main__":
    unittest.main()

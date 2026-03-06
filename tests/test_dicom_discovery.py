import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import dicom_discovery


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

    def test_can_parse_as_dicom_handles_parser_errors(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            file_path = base / "noext"
            file_path.write_text("x")
            with patch("dicom_discovery.pydicom.dcmread", side_effect=ValueError("bad")):
                self.assertFalse(dicom_discovery.can_parse_as_dicom(file_path))

    def test_is_dicom_candidate_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            target = base / "real.dcm"
            target.write_bytes(b"x")
            link = base / "link.dcm"
            link.symlink_to(target)
            self.assertFalse(dicom_discovery.is_dicom_candidate(link))


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

from dicom_browser.archive_utils import safe_archive_member_path


class ArchiveUtilsTests(unittest.TestCase):
    def test_safe_archive_member_path_allows_nested_member(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            member_path = safe_archive_member_path(root, "patient/study/file.dcm")

        self.assertEqual(member_path, (root / "patient" / "study" / "file.dcm").resolve())

    def test_safe_archive_member_path_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaises(ValueError):
                safe_archive_member_path(root, "../outside.dcm")


if __name__ == "__main__":
    unittest.main()

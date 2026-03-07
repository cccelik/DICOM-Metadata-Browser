import tempfile
import unittest
from pathlib import Path

from dicom_browser.extract_metadata import DICOMMetadata
from dicom_browser import store_metadata


class StoreMetadataIntegrationTests(unittest.TestCase):
    def test_init_database_creates_required_tables_and_columns(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = str(Path(td) / "meta.db")
            conn = store_metadata.init_database(db_path, optimize=False)
            tables = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            self.assertIn("dicom_metadata", tables)
            self.assertIn("private_tag", tables)

            cols = {row[1] for row in conn.execute("PRAGMA table_info(dicom_metadata)").fetchall()}
            self.assertIn("scan_root", cols)
            self.assertIn("protocol_name", cols)
            self.assertIn("is_representative", cols)
            self.assertIn("rows", cols)
            self.assertIn("series_type", cols)
            self.assertIn("reconstruction_method", cols)
            conn.close()

    def test_insert_metadata_and_study_exists(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = str(Path(td) / "meta.db")
            conn = store_metadata.init_database(db_path, optimize=False)
            meta = DICOMMetadata(
                patient_id="P1",
                study_instance_uid="STUDY1",
                series_instance_uid="SERIES1",
                sop_instance_uid="SOP1",
            )
            inserted, reason = store_metadata.insert_metadata(
                conn,
                meta,
                "scan/file1.dcm",
                scan_root="/root",
                commit=True,
            )
            self.assertTrue(inserted)
            self.assertEqual(reason, "inserted")
            self.assertTrue(store_metadata.study_exists(conn, "STUDY1"))
            self.assertFalse(store_metadata.study_exists(conn, "STUDY2"))
            conn.close()

    def test_insert_metadata_duplicate_series(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = str(Path(td) / "meta.db")
            conn = store_metadata.init_database(db_path, optimize=False)
            meta1 = DICOMMetadata(study_instance_uid="S1", series_instance_uid="SERIES1", sop_instance_uid="A")
            meta2 = DICOMMetadata(study_instance_uid="S1", series_instance_uid="SERIES1", sop_instance_uid="B")
            first = store_metadata.insert_metadata(conn, meta1, "a.dcm", commit=True)
            second = store_metadata.insert_metadata(conn, meta2, "b.dcm", commit=True)
            self.assertEqual(first, (True, "inserted"))
            self.assertEqual(second, (False, "series_exists"))
            conn.close()

    def test_insert_private_tags_deduplicates_unique_constraint(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = str(Path(td) / "meta.db")
            conn = store_metadata.init_database(db_path, optimize=False)
            meta = DICOMMetadata(
                study_instance_uid="STUDY1",
                series_instance_uid="SERIES1",
                sop_instance_uid="SOP1",
                manufacturer="SIEMENS",
                modality="PT",
            )
            tag = {
                "sop_instance_uid": "SOP1",
                "group_hex": "0029",
                "element_hex": "1010",
                "creator": "SIEMENS CSA HEADER",
                "vr": "OB",
                "value_text": "abc",
                "value_num": None,
                "value_json": None,
                "value_hex": None,
                "byte_len": 3,
                "value_hash": "hash-1",
                "classification": "vendor_semantic",
            }
            store_metadata.insert_private_tags(conn, meta, "f1.dcm", [tag], commit=True)
            store_metadata.insert_private_tags(conn, meta, "f1.dcm", [tag], commit=True)
            count = conn.execute("SELECT COUNT(*) FROM private_tag").fetchone()[0]
            self.assertEqual(count, 1)
            conn.close()

    def test_insert_metadata_persists_private_tags(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = str(Path(td) / "meta.db")
            conn = store_metadata.init_database(db_path, optimize=False)
            meta = DICOMMetadata(
                study_instance_uid="S1",
                series_instance_uid="SERIES1",
                sop_instance_uid="SOP1",
                private_tags=[
                    {
                        "sop_instance_uid": "SOP1",
                        "group_hex": "0029",
                        "element_hex": "1010",
                        "creator": "SIEMENS CSA HEADER",
                        "vr": "OB",
                        "value_text": "payload",
                        "value_num": None,
                        "value_json": None,
                        "value_hex": None,
                        "byte_len": 7,
                        "value_hash": "hash-1",
                        "classification": "vendor_semantic",
                    }
                ],
            )
            inserted, reason = store_metadata.insert_metadata(conn, meta, "rel/path.dcm", commit=True)
            self.assertEqual((inserted, reason), (True, "inserted"))
            private_row = conn.execute(
                "SELECT series_instance_uid, creator, value_text FROM private_tag"
            ).fetchone()
            self.assertEqual(private_row, ("SERIES1", "SIEMENS CSA HEADER", "payload"))
            conn.close()

    def test_insert_metadata_duplicate_with_skip_disabled_returns_already_exists(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = str(Path(td) / "meta.db")
            conn = store_metadata.init_database(db_path, optimize=False)
            meta = DICOMMetadata(study_instance_uid="S1", series_instance_uid="SERIES1", sop_instance_uid="A")
            first = store_metadata.insert_metadata(conn, meta, "a.dcm", commit=True)
            second = store_metadata.insert_metadata(conn, meta, "a2.dcm", skip_existing=False, commit=True)
            self.assertEqual(first, (True, "inserted"))
            self.assertEqual(second, (False, "already_exists"))
            conn.close()

    def test_insert_private_tags_empty_is_noop(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = str(Path(td) / "meta.db")
            conn = store_metadata.init_database(db_path, optimize=False)
            meta = DICOMMetadata(study_instance_uid="S1", series_instance_uid="SERIES1", sop_instance_uid="SOP1")
            store_metadata.insert_private_tags(conn, meta, "f.dcm", [], commit=True)
            count = conn.execute("SELECT COUNT(*) FROM private_tag").fetchone()[0]
            self.assertEqual(count, 0)
            conn.close()


if __name__ == "__main__":
    unittest.main()

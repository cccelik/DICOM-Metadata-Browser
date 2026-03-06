import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import store_metadata
import webui


class WebUiAnonymizedExportTests(unittest.TestCase):
    def _create_seed_db(self, db_path: Path) -> None:
        conn = store_metadata.init_database(str(db_path), optimize=False)
        conn.execute(
            """
            INSERT INTO dicom_metadata (
                patient_name, patient_id, patient_birth_date,
                study_description, series_description, protocol_name,
                study_id, file_path, scan_root,
                csa_image_header_json, csa_series_header_json,
                study_instance_uid, series_instance_uid, sop_instance_uid
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Max^Mustermann",
                "PATIENT-001",
                "19900101",
                "Demo Study Description",
                "Demo Series Description",
                "Demo Protocol",
                "STUDY-001",
                r"scanner_x\demo_study\patient_protocol\file.ima",
                r"X:\demo_root",
                '{"PatientProtocol":"DemoProtocol"}',
                '{"PatientStatistics":"DemoStats"}',
                "STUDY-UID-001",
                "SERIES-UID-001",
                "SOP-UID-001",
            ),
        )
        conn.execute(
            """
            INSERT INTO private_tag (
                sop_instance_uid, series_instance_uid, study_instance_uid,
                file_path, creator, classification, value_text, value_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "SOP-UID-001",
                "SERIES-UID-001",
                "STUDY-UID-001",
                r"X:\demo_root\path\file.ima",
                "VENDOR PRIVATE HEADER",
                "vendor_semantic",
                "demo protocol context",
                "hash-demo-001",
            ),
        )
        conn.commit()
        conn.close()

    def _export_and_open(self, client, query: str, out_path: Path) -> sqlite3.Connection:
        response = client.get(query)
        self.assertEqual(response.status_code, 200, response.status)
        out_path.write_bytes(response.data)
        response.close()
        return sqlite3.connect(str(out_path))

    def test_export_anonymized_defaults_scrub_sensitive_fields(self):
        with tempfile.TemporaryDirectory() as td:
            db_dir = Path(td)
            db_path = db_dir / "sample.db"
            out_path = db_dir / "anonymized.db"
            self._create_seed_db(db_path)

            with patch.object(webui, "DATABANK_DIR", db_dir):
                client = webui.app.test_client()
                conn = self._export_and_open(client, "/databanks/export-anonymized?db=sample.db", out_path)
                row = conn.execute(
                    """
                    SELECT patient_name, patient_id, study_description, series_description, protocol_name,
                           file_path, scan_root, csa_image_header_json, csa_series_header_json
                    FROM dicom_metadata
                    """
                ).fetchone()
                self.assertIsNotNone(row[0])
                self.assertNotEqual(row[0], "Max^Mustermann")
                self.assertIsNotNone(row[1])
                self.assertNotEqual(row[1], "PATIENT-001")
                # Blanked fields
                self.assertIsNone(row[2])
                self.assertIsNone(row[3])
                self.assertIsNone(row[4])
                self.assertIsNotNone(row[5])  # anonymized token for file path
                self.assertIsNone(row[6])      # scan root scrubbed when file_path enabled
                self.assertIsNone(row[7])
                self.assertIsNone(row[8])

                private = conn.execute(
                    "SELECT file_path, value_text, value_hash FROM private_tag"
                ).fetchone()
                self.assertEqual(private, (None, None, None))
                conn.close()

    def test_export_anonymized_keeps_defaults_even_with_custom_fields(self):
        with tempfile.TemporaryDirectory() as td:
            db_dir = Path(td)
            db_path = db_dir / "sample.db"
            out_path = db_dir / "anonymized_custom.db"
            self._create_seed_db(db_path)

            with patch.object(webui, "DATABANK_DIR", db_dir):
                client = webui.app.test_client()
                # Request only study_id explicitly; defaults must still apply.
                conn = self._export_and_open(
                    client,
                    "/databanks/export-anonymized?db=sample.db&fields=study_id",
                    out_path,
                )
                row = conn.execute(
                    "SELECT patient_name, patient_id, file_path, scan_root, study_id FROM dicom_metadata"
                ).fetchone()
                self.assertNotEqual(row[0], "Max^Mustermann")
                self.assertNotEqual(row[1], "PATIENT-001")
                self.assertIsNotNone(row[2])  # default field still anonymized
                self.assertIsNone(row[3])      # scrubbed due default file_path behavior
                self.assertIsNotNone(row[4])   # requested field anonymized
                conn.close()

    def test_export_anonymized_missing_db_returns_404(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.object(webui, "DATABANK_DIR", Path(td)):
                client = webui.app.test_client()
                response = client.get("/databanks/export-anonymized?db=does_not_exist.db")
                self.assertEqual(response.status_code, 404)

    def test_export_anonymized_sets_sanitized_download_name(self):
        with tempfile.TemporaryDirectory() as td:
            db_dir = Path(td)
            db_path = db_dir / "sample weird name.db"
            self._create_seed_db(db_path)

            with patch.object(webui, "DATABANK_DIR", db_dir):
                client = webui.app.test_client()
                response = client.get("/databanks/export-anonymized?db=sample weird name.db")
                self.assertEqual(response.status_code, 200)
                content_disposition = response.headers.get("Content-Disposition", "")
                self.assertIn("attachment;", content_disposition)
                self.assertIn("sample_weird_name_anonymized.db", content_disposition)
                response.close()


if __name__ == "__main__":
    unittest.main()

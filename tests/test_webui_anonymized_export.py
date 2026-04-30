import sqlite3
import tempfile
import unittest
from csv import reader
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from dicom_browser import store_metadata
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

    def test_export_databank_csv_uses_default_fields_and_rows(self):
        with tempfile.TemporaryDirectory() as td:
            db_dir = Path(td)
            db_path = db_dir / "sample.db"
            conn = store_metadata.init_database(str(db_path), optimize=False)
            conn.execute(
                """
                INSERT INTO dicom_metadata (
                    patient_id, patient_name, patient_birth_date, patient_sex, patient_age, patient_weight, patient_size,
                    study_instance_uid, study_date, study_time, study_description,
                    series_instance_uid, series_number, series_date, series_time, series_description, protocol_name, modality,
                    body_part_examined, manufacturer, manufacturer_model_name,
                    scanning_sequence, sequence_variant, scan_options, convolution_kernel, reconstruction_method,
                    radiopharmaceutical, injected_activity, injected_activity_unit, injection_time, injection_date,
                    half_life, decay_correction, radiopharmaceutical_volume, radionuclide_total_dose,
                    pixel_spacing, rows, number_of_frames, number_of_slices, series_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "PAT-1", "Doe^Jane", "19900101", "F", "035Y", 70.0, 1.70,
                    "STUDY-1", "20260301", "101112", "Demo Study",
                    "SERIES-1", 1, "20260301", "101500", "Demo Series", "FDG_TK_Axilla", "PT",
                    "WHOLE BODY", "Siemens", "Biograph",
                    "SEQ", "VAR", "OPT", "All-pass", "PSF+TOF 4i5s",
                    "FDG", 120000000, "Bq", "091500", "20260301",
                    6586.2, "START", 12.5, 120000000,
                    "[1.65, 1.65]", 440, 1, 440, "WHOLE BODY\\IMAGE"
                ),
            )
            conn.commit()
            conn.close()

            with patch.object(webui, "DATABANK_DIR", db_dir):
                client = webui.app.test_client()
                response = client.get("/databanks/export.csv?db=sample.db")
                self.assertEqual(response.status_code, 200, response.status)
                content = response.data.decode("utf-8")
                rows = list(reader(StringIO(content)))
                self.assertEqual(rows[0][0:7], ["Patient Name", "Patient ID", "Birth Date", "Sex", "Age", "Weight", "Height"])
                self.assertIn("Series Type", rows[0])
                self.assertIn("Rows", rows[0])
                self.assertIn("Reconstruction Method", rows[0])
                data_row = rows[1]
                self.assertIn("Doe Jane", data_row)
                self.assertIn("Demo Study", data_row)
                self.assertIn("PSF+TOF 4i5s", data_row)
                self.assertIn("WHOLE BODY\\IMAGE", data_row)
                self.assertIn("440", data_row)
                response.close()

    def test_export_databank_csv_can_anonymize_selected_fields(self):
        with tempfile.TemporaryDirectory() as td:
            db_dir = Path(td)
            db_path = db_dir / "sample.db"
            conn = store_metadata.init_database(str(db_path), optimize=False)
            conn.execute(
                """
                INSERT INTO dicom_metadata (
                    patient_name, patient_id, study_description, series_description, protocol_name,
                    file_path, study_instance_uid, series_instance_uid, sop_instance_uid
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "Max^Mustermann", "PAT-001", "Demo Study", "Demo Series", "Demo Protocol",
                    "relative/path/file.dcm", "STUDY-1", "SERIES-1", "SOP-1",
                ),
            )
            conn.commit()
            conn.close()

            with patch.object(webui, "DATABANK_DIR", db_dir):
                client = webui.app.test_client()
                response = client.get(
                    "/databanks/export.csv?db=sample.db&anonymize=1&fields=patient_name&fields=patient_id"
                )
                self.assertEqual(response.status_code, 200, response.status)
                rows = list(reader(StringIO(response.data.decode("utf-8"))))
                self.assertEqual(rows[0], ["Patient Name", "Patient ID"])
                self.assertNotEqual(rows[1][0], "Max Mustermann")
                self.assertNotEqual(rows[1][1], "PAT-001")
                self.assertTrue(rows[1][0].startswith("PATIENTNAM"))
                self.assertTrue(rows[1][1].startswith("PATIENTID"))
                response.close()

    def test_export_study_csv_can_anonymize_and_blank_default_fields(self):
        with tempfile.TemporaryDirectory() as td:
            db_dir = Path(td)
            db_path = db_dir / "sample.db"
            conn = store_metadata.init_database(str(db_path), optimize=False)
            conn.execute(
                """
                INSERT INTO dicom_metadata (
                    patient_name, patient_id, study_description, series_description, protocol_name,
                    study_instance_uid, series_instance_uid, sop_instance_uid
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "Max^Mustermann", "PAT-001", "Demo Study", "Demo Series", "Demo Protocol",
                    "STUDY-1", "SERIES-1", "SOP-1",
                ),
            )
            conn.commit()
            conn.close()

            with patch.object(webui, "DATABANK_DIR", db_dir):
                client = webui.app.test_client()
                response = client.get(
                    "/study/STUDY-1/export.csv?db=sample.db"
                    "&fields=patient_name&fields=study_description"
                    "&anonymize=1"
                )
                self.assertEqual(response.status_code, 200, response.status)
                rows = list(reader(StringIO(response.data.decode("utf-8"))))
                self.assertEqual(rows[0], ["Patient Name", "Description"])
                self.assertTrue(rows[1][0].startswith("PATIENTNAM"))
                self.assertEqual(rows[1][1], "")
                response.close()

    def test_export_csv_uses_lang_query_over_session_language(self):
        with tempfile.TemporaryDirectory() as td:
            db_dir = Path(td)
            db_path = db_dir / "sample.db"
            conn = store_metadata.init_database(str(db_path), optimize=False)
            conn.execute(
                """
                INSERT INTO dicom_metadata (
                    patient_name, patient_id, study_instance_uid, series_instance_uid, sop_instance_uid
                ) VALUES (?, ?, ?, ?, ?)
                """,
                ("Max^Mustermann", "PAT-001", "STUDY-1", "SERIES-1", "SOP-1"),
            )
            conn.commit()
            conn.close()

            with patch.object(webui, "DATABANK_DIR", db_dir):
                client = webui.app.test_client()
                with client.session_transaction() as session:
                    session["language"] = "en"
                response = client.get("/databanks/export.csv?db=sample.db&lang=de&fields=patient_name")
                self.assertEqual(response.status_code, 200, response.status)
                rows = list(reader(StringIO(response.data.decode("utf-8"))))
                self.assertEqual(rows[0], ["Patientenname"])
                response.close()

    def test_copy_selected_studies_creates_filtered_databank(self):
        with tempfile.TemporaryDirectory() as td:
            db_dir = Path(td)
            source_path = db_dir / "source.db"
            conn = store_metadata.init_database(str(source_path), optimize=False)
            conn.executemany(
                """
                INSERT INTO dicom_metadata (
                    patient_name, patient_id, study_instance_uid, series_instance_uid, sop_instance_uid, modality
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    ("Doe^Jane", "PAT-1", "STUDY-1", "SERIES-1", "SOP-1", "PT"),
                    ("Doe^Jane", "PAT-1", "STUDY-1", "SERIES-2", "SOP-2", "CT"),
                    ("Roe^John", "PAT-2", "STUDY-2", "SERIES-3", "SOP-3", "MR"),
                ],
            )
            conn.execute(
                """
                INSERT INTO private_tag (
                    sop_instance_uid, series_instance_uid, study_instance_uid,
                    file_path, creator, group_hex, element_hex, value_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("SOP-1", "SERIES-1", "STUDY-1", "file.dcm", "CREATOR", "0019", "1001", "hash-1"),
            )
            conn.commit()
            conn.close()

            with patch.object(webui, "DATABANK_DIR", db_dir):
                client = webui.app.test_client()
                response = client.post(
                    "/databanks/copy-studies",
                    data={
                        "db": "source.db",
                        "target_name": "filtered",
                        "study_uids": ["STUDY-1"],
                    },
                )
                self.assertEqual(response.status_code, 200, response.status)
                payload = response.get_json()
                self.assertTrue(payload["success"])
                self.assertEqual(payload["name"], "filtered.db")
                self.assertEqual(payload["study_count"], 1)
                self.assertEqual(payload["metadata_rows"], 2)
                self.assertEqual(payload["private_tag_rows"], 1)

                copied = sqlite3.connect(str(db_dir / "filtered.db"))
                copied_rows = copied.execute(
                    "SELECT study_instance_uid, series_instance_uid FROM dicom_metadata ORDER BY series_instance_uid"
                ).fetchall()
                self.assertEqual(copied_rows, [("STUDY-1", "SERIES-1"), ("STUDY-1", "SERIES-2")])
                private_count = copied.execute("SELECT COUNT(*) FROM private_tag").fetchone()[0]
                self.assertEqual(private_count, 1)
                copied.close()

    def test_copy_selected_studies_can_use_existing_target(self):
        with tempfile.TemporaryDirectory() as td:
            db_dir = Path(td)
            source_conn = store_metadata.init_database(str(db_dir / "source.db"), optimize=False)
            source_conn.execute(
                """
                INSERT INTO dicom_metadata (
                    patient_name, patient_id, study_instance_uid, series_instance_uid, sop_instance_uid, modality
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("Doe^Jane", "PAT-1", "STUDY-1", "SERIES-1", "SOP-1", "PT"),
            )
            source_conn.commit()
            source_conn.close()
            target_conn = store_metadata.init_database(str(db_dir / "target.db"), optimize=False)
            target_conn.close()

            with patch.object(webui, "DATABANK_DIR", db_dir):
                client = webui.app.test_client()
                response = client.post(
                    "/databanks/copy-studies",
                    data={
                        "db": "source.db",
                        "target_name": "target.db",
                        "study_uids": ["STUDY-1"],
                    },
                )
                self.assertEqual(response.status_code, 200, response.status)
                copied = sqlite3.connect(str(db_dir / "target.db"))
                copied_count = copied.execute("SELECT COUNT(*) FROM dicom_metadata").fetchone()[0]
                self.assertEqual(copied_count, 1)
                copied.close()

    def test_move_selected_studies_deletes_from_source_and_keeps_target(self):
        with tempfile.TemporaryDirectory() as td:
            db_dir = Path(td)
            source_conn = store_metadata.init_database(str(db_dir / "source.db"), optimize=False)
            source_conn.executemany(
                """
                INSERT INTO dicom_metadata (
                    patient_name, patient_id, study_instance_uid, series_instance_uid, sop_instance_uid, modality
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    ("Doe^Jane", "PAT-1", "STUDY-1", "SERIES-1", "SOP-1", "PT"),
                    ("Roe^John", "PAT-2", "STUDY-2", "SERIES-2", "SOP-2", "CT"),
                ],
            )
            source_conn.execute(
                """
                INSERT INTO private_tag (
                    sop_instance_uid, series_instance_uid, study_instance_uid,
                    file_path, creator, group_hex, element_hex, value_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("SOP-1", "SERIES-1", "STUDY-1", "file.dcm", "CREATOR", "0019", "1001", "hash-1"),
            )
            source_conn.commit()
            source_conn.close()

            with patch.object(webui, "DATABANK_DIR", db_dir):
                client = webui.app.test_client()
                response = client.post(
                    "/databanks/copy-studies",
                    data={
                        "db": "source.db",
                        "target_name": "moved.db",
                        "action": "move",
                        "study_uids": ["STUDY-1"],
                    },
                )
                self.assertEqual(response.status_code, 200, response.status)
                payload = response.get_json()
                self.assertEqual(payload["deleted_metadata_rows"], 1)
                self.assertEqual(payload["deleted_private_tag_rows"], 1)

                source = sqlite3.connect(str(db_dir / "source.db"))
                remaining = source.execute(
                    "SELECT study_instance_uid FROM dicom_metadata"
                ).fetchall()
                private_count = source.execute("SELECT COUNT(*) FROM private_tag").fetchone()[0]
                source.close()
                self.assertEqual(remaining, [("STUDY-2",)])
                self.assertEqual(private_count, 0)

                target = sqlite3.connect(str(db_dir / "moved.db"))
                moved = target.execute("SELECT study_instance_uid FROM dicom_metadata").fetchall()
                target.close()
                self.assertEqual(moved, [("STUDY-1",)])

    def test_rename_databank(self):
        with tempfile.TemporaryDirectory() as td:
            db_dir = Path(td)
            store_metadata.init_database(str(db_dir / "old.db"), optimize=False).close()

            with patch.object(webui, "DATABANK_DIR", db_dir):
                client = webui.app.test_client()
                response = client.post(
                    "/databanks/rename",
                    data={"db": "old.db", "new_name": "renamed"},
                )
                self.assertEqual(response.status_code, 200, response.status)
                payload = response.get_json()
                self.assertEqual(payload["name"], "renamed.db")
                self.assertFalse((db_dir / "old.db").exists())
                self.assertTrue((db_dir / "renamed.db").exists())


if __name__ == "__main__":
    unittest.main()

import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from dicom_browser.store_metadata import init_database
from dicom_browser.study_service import build_study_detail_payload, resolve_display_path


class StudyServiceTests(unittest.TestCase):
    def test_resolve_display_path_handles_absolute_and_zip_paths(self):
        abs_path, label = resolve_display_path("/ignored", "/tmp/file.dcm")
        self.assertEqual(abs_path, "/tmp/file.dcm")
        self.assertIsNone(label)

        zip_path, zip_label = resolve_display_path("zip:upload.zip", "nested/file.dcm")
        self.assertEqual(zip_path, str(Path("upload.zip") / "nested/file.dcm"))
        self.assertEqual(zip_label, "Extracted from uploaded zip file: upload.zip")

    def test_build_study_detail_payload_enriches_private_tags_and_delay(self):
        with TemporaryDirectory() as td:
            db_path = Path(td) / "study.db"
            conn = init_database(str(db_path), optimize=False)
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                INSERT INTO dicom_metadata (
                    study_instance_uid, series_instance_uid, patient_name, patient_weight, patient_size,
                    study_date, study_time, series_number, series_description, modality, scan_root,
                    acquisition_date, acquisition_time, injection_date, injection_time, injected_activity,
                    half_life, file_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "study-1", "series-1", "Doe^John", 80.0, 1.8,
                    "20260301", "120000", 1, "PET Series", "PT", "zip:upload.zip",
                    "20260301", "130000", "20260301", "120000", 120000000.0,
                    3600.0, "nested/file.dcm",
                ),
            )
            conn.execute(
                """
                INSERT INTO private_tag (
                    series_instance_uid, study_instance_uid, creator, group_hex, element_hex,
                    value_text, value_hash, classification
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "series-1", "study-1", "PIPELINE", "0019", "1001",
                    "20260301123456", "hash-1", "pipeline_provenance",
                ),
            )
            conn.execute(
                """
                INSERT INTO private_tag (
                    series_instance_uid, study_instance_uid, creator, group_hex, element_hex,
                    value_text, value_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "series-1", "study-1", "SIEMENS CSA HEADER", "0029", "1010",
                    "<PetDoseReportData><m_StatisticsNameVector>InjectedDose</m_StatisticsNameVector><m_StatisticsValueVector1>250</m_StatisticsValueVector1></PetDoseReportData>",
                    "hash-2",
                ),
            )
            conn.commit()

            payload = build_study_detail_payload(
                conn,
                "study-1",
                calculate_activity_at_scan=lambda injected, half_life, delay: injected / 2,
            )

            self.assertIsNotNone(payload)
            self.assertEqual(payload["study_info"]["patient_name_display"], "Doe John")
            self.assertEqual(payload["study_info"]["study_absolute_path_labels"], ["Extracted from uploaded zip file: upload.zip"])
            self.assertEqual(payload["export_modalities"], ["PT"])
            self.assertAlmostEqual(payload["study_info"]["bmi"], 80.0 / (1.8 * 1.8), places=3)

            series = payload["series"][0]
            self.assertEqual(series["absolute_file_path"], str(Path("upload.zip") / "nested/file.dcm"))
            self.assertAlmostEqual(series["injection_delay_minutes"], 60.0, places=3)
            self.assertEqual(series["injection_delay"], "1.0 hours (60 min)")
            self.assertEqual(series["pipeline_provenance"][0]["display_value"], "01/03/2026 12:34:56")
            self.assertEqual(series["pet_dose_report"][0]["name"], "InjectedDose")
            self.assertIn("activity_at_scan", series)


if __name__ == "__main__":
    unittest.main()

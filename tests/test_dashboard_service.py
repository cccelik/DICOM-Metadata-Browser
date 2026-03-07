import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from dashboard_service import build_dashboard_payload
from store_metadata import init_database


class DashboardServiceTests(unittest.TestCase):
    def test_build_dashboard_payload_returns_expected_summary(self):
        with TemporaryDirectory() as td:
            db_path = Path(td) / "dashboard.db"
            conn = init_database(str(db_path), optimize=False)
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                INSERT INTO private_tag (
                    series_instance_uid, study_instance_uid, creator, group_hex, element_hex,
                    value_text, value_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                ("series-1", "study-1", "CTP", "0013", "1010", "Collection-A", "hash-1"),
            )
            conn.commit()
            conn.close()

            study_summary = [{
                "study_instance_uid": "study-1",
                "patient_weight": "80",
                "patient_size": "1.8",
                "patient_birth_date": "19800101",
                "patient_sex": "M",
                "patient_age": "046Y",
                "study_date": "20260301",
                "study_time": "120000",
            }]
            study_modalities = {"study-1": {"PT"}}
            representative_series_rows = [{
                "study_instance_uid": "study-1",
                "series_instance_uid": "series-1",
                "sop_instance_uid": "sop-1",
                "modality": "PT",
                "radiopharmaceutical": "FDG",
                "manufacturer": "Siemens",
                "manufacturer_model_name": "Biograph",
                "software_version": "1.0",
                "series_description": "Whole Body",
                "study_date": "20260301",
                "study_time": "120000",
                "injection_date": "20260301",
                "injection_time": "120000",
                "acquisition_date": "20260301",
                "acquisition_time": "130000",
                "series_time": "123000",
                "injected_activity": 240000000.0,
                "patient_weight": "80",
                "ctdivol": 5.0,
                "dlp": 120.0,
                "csa_series_header_hash": "csa-1",
                "number_of_slices": 64,
            }]

            payload = build_dashboard_payload(
                study_summary=study_summary,
                study_modalities=study_modalities,
                representative_series_rows=representative_series_rows,
                db_path=str(db_path),
                parse_time_to_24hour=lambda value: (int(str(value)[:2]), int(str(value)[2:4]), int(str(value)[4:6])),
                calculate_injection_delay=lambda *args, **kwargs: (60.0, None),
                compute_delay_status=lambda row: (60.0, "ok"),
                has_time_conflict=lambda row: False,
                has_radiopharm=lambda row: bool(row.get("radiopharmaceutical")),
            )

            self.assertEqual(payload["stats"]["total_series"], 1)
            self.assertEqual(payload["stats"]["total_studies"], 1)
            self.assertEqual(payload["stats"]["radiopharmaceuticals"], {"FDG": 1})
            self.assertEqual(payload["stats"]["radiopharmaceutical_total_series"], 1)
            self.assertEqual(payload["stats"]["uptake_time"]["count"], 1)
            self.assertEqual(payload["completeness_stats"]["counts"]["dose"], 1)
            self.assertEqual(payload["timing_stats"]["negative"], 0)
            self.assertEqual(payload["timing_stats"]["study_time_conflict"], 0)
            self.assertEqual(payload["derived_stats"]["ctp_labels"][0]["value_text"], "Collection-A")
            self.assertEqual(payload["qa_scores"][5], 1)
            self.assertTrue(payload["uptake_histogram"]["values"])
            self.assertTrue(payload["dose_histogram"]["values"])


if __name__ == "__main__":
    unittest.main()

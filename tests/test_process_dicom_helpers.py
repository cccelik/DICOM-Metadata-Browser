import sqlite3
import tempfile
import unittest
from pathlib import Path

import process_dicom
from dicom_browser import store_metadata


class ProcessDicomHelpersTests(unittest.TestCase):
    def test_parse_db_float(self):
        self.assertEqual(process_dicom._parse_db_float("3.5"), 3.5)
        self.assertEqual(process_dicom._parse_db_float(4), 4.0)
        self.assertIsNone(process_dicom._parse_db_float(None))
        self.assertIsNone(process_dicom._parse_db_float("x"))

    def test_parse_time_to_24hour(self):
        self.assertEqual(process_dicom._parse_time_to_24hour("123456"), (12, 34, 56))
        self.assertEqual(process_dicom._parse_time_to_24hour("123456.9"), (12, 34, 56))
        self.assertIsNone(process_dicom._parse_time_to_24hour("bad"))
        self.assertIsNone(process_dicom._parse_time_to_24hour(None))

    def test_calculate_injection_delay(self):
        delay = process_dicom._calculate_injection_delay(
            "20260301", "120000", "20260301", "130000"
        )
        self.assertAlmostEqual(delay, 60.0, places=2)
        delay_negative = process_dicom._calculate_injection_delay(
            "20260301", "130000", "20260301", "120000"
        )
        self.assertAlmostEqual(delay_negative, -60.0, places=2)
        self.assertIsNone(process_dicom._calculate_injection_delay(None, "120000", "20260301", "130000"))

    def test_compute_delay_minutes(self):
        row = {
            "injection_time": "120000",
            "acquisition_time": "130000",
            "injection_date": "20260301",
            "acquisition_date": "20260301",
        }
        self.assertAlmostEqual(process_dicom._compute_delay_minutes(row), 60.0, places=2)

        row_fallback = {
            "injection_time": "120000",
            "acquisition_time": "130000",
            "study_date": "20260301",
        }
        self.assertAlmostEqual(process_dicom._compute_delay_minutes(row_fallback), 60.0, places=2)

        self.assertIsNone(process_dicom._compute_delay_minutes({"study_date": "20260301"}))

    def test_compute_dose_per_kg(self):
        row = {"patient_weight": "70", "injected_activity": "210"}
        self.assertAlmostEqual(process_dicom._compute_dose_per_kg(row), 3.0, places=3)
        row_bq = {"patient_weight": "70", "injected_activity": "210000000"}
        self.assertAlmostEqual(process_dicom._compute_dose_per_kg(row_bq), 3.0, places=3)
        row_study_weight = {"study_patient_weight": "80", "injected_activity": "320"}
        self.assertAlmostEqual(process_dicom._compute_dose_per_kg(row_study_weight), 4.0, places=3)
        self.assertIsNone(process_dicom._compute_dose_per_kg({"patient_weight": 0, "injected_activity": 210}))

    def test_select_representative_series_prefers_richer_row(self):
        rows = [
            {
                "study_instance_uid": "study-1",
                "series_instance_uid": "s1",
                "modality": "CT",
                "patient_weight": None,
                "injected_activity": None,
                "injection_date": None,
                "injection_time": None,
                "acquisition_date": None,
                "acquisition_time": None,
                "study_date": "20260301",
            },
            {
                "study_instance_uid": "study-1",
                "series_instance_uid": "s2",
                "modality": "PT",
                "patient_weight": "70",
                "injected_activity": "210",
                "injection_date": "20260301",
                "injection_time": "120000",
                "acquisition_date": "20260301",
                "acquisition_time": "130000",
                "study_date": "20260301",
            },
        ]
        keep = process_dicom._select_representative_series(rows)
        self.assertEqual(keep, ["s2"])

    def test_filter_existing_paths(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            a = base / "a.dcm"
            b = base / "b.dcm"
            a.write_bytes(b"x")
            b.write_bytes(b"y")
            filtered, skipped = process_dicom._filter_existing_paths(
                [a, b], base, {"a.dcm"}
            )
            self.assertEqual([p.name for p in filtered], ["b.dcm"])
            self.assertEqual(skipped, 1)

    def test_filter_existing_paths_when_no_existing_set(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            a = base / "a.dcm"
            a.write_bytes(b"x")
            filtered, skipped = process_dicom._filter_existing_paths([a], base, None)
            self.assertEqual([p.name for p in filtered], ["a.dcm"])
            self.assertEqual(skipped, 0)

    def test_prune_non_representative_series(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = str(Path(td) / "test.db")
            conn = store_metadata.init_database(db_path, optimize=False)
            # study-1 has two series, s2 should win by richer metadata.
            conn.execute(
                """
                INSERT INTO dicom_metadata
                (series_instance_uid, study_instance_uid, modality, patient_weight, injected_activity,
                 injection_date, injection_time, acquisition_date, acquisition_time, study_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("s1", "study-1", "CT", None, None, None, None, None, None, "20260301"),
            )
            conn.execute(
                """
                INSERT INTO dicom_metadata
                (series_instance_uid, study_instance_uid, modality, patient_weight, injected_activity,
                 injection_date, injection_time, acquisition_date, acquisition_time, study_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("s2", "study-1", "PT", 70.0, 210.0, "20260301", "120000", "20260301", "130000", "20260301"),
            )
            conn.commit()
            pruned = process_dicom.prune_non_representative_series(conn)
            self.assertEqual(pruned, 1)
            rep = conn.execute(
                "SELECT series_instance_uid FROM dicom_metadata WHERE is_representative = 1"
            ).fetchall()
            self.assertEqual([r[0] for r in rep], ["s2"])
            conn.close()

    def test_prune_non_representative_series_empty_db(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = str(Path(td) / "test.db")
            conn = store_metadata.init_database(db_path, optimize=False)
            self.assertEqual(process_dicom.prune_non_representative_series(conn), 0)
            conn.close()


if __name__ == "__main__":
    unittest.main()

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import webui


class WebUiUtilsTests(unittest.TestCase):
    def test_normalize_db_name_defaults_and_suffix(self):
        self.assertEqual(webui.normalize_db_name(None), webui.DEFAULT_DB_NAME)
        self.assertEqual(webui.normalize_db_name(""), webui.DEFAULT_DB_NAME)
        self.assertEqual(webui.normalize_db_name("sample"), "sample.db")
        self.assertEqual(webui.normalize_db_name("sample.db"), "sample.db")

    def test_normalize_db_name_strips_path(self):
        self.assertEqual(webui.normalize_db_name("/tmp/a/b/mydb"), "mydb.db")
        self.assertEqual(webui.normalize_db_name("../unsafe/path.db"), "path.db")

    def test_sanitize_filename(self):
        self.assertEqual(webui.sanitize_filename("a b/c"), "a_b_c")
        self.assertEqual(webui.sanitize_filename(".."), "export")

    def test_format_patient_name(self):
        self.assertEqual(webui.format_patient_name(None), "")
        self.assertEqual(webui.format_patient_name(""), "")
        self.assertEqual(webui.format_patient_name("Doe^John"), "Doe John")
        self.assertEqual(webui.format_patient_name("anonymous^123"), "anonymous 123")

    def test_is_radiopharm_modality(self):
        self.assertTrue(webui.is_radiopharm_modality("PT"))
        self.assertTrue(webui.is_radiopharm_modality("pet/ct"))
        self.assertFalse(webui.is_radiopharm_modality("CT"))

    def test_calculate_injection_delay(self):
        delay, err = webui.calculate_injection_delay(
            "20260301", "120000", "20260301", "130000"
        )
        self.assertEqual(err, None)
        self.assertAlmostEqual(delay, 60.0, places=2)

        delay_neg, err_neg = webui.calculate_injection_delay(
            "20260301", "130000", "20260301", "120000"
        )
        self.assertEqual((delay_neg, err_neg), (None, None))

    def test_format_private_timestamp(self):
        self.assertEqual(
            webui.format_private_timestamp("20260301123456"),
            "01/03/2026 12:34:56",
        )
        self.assertEqual(webui.format_private_timestamp("123456.789"), "12:34:56.7")
        self.assertEqual(webui.format_private_timestamp(""), None)

    def test_parse_pet_dose_report(self):
        xml = """
        <root>
          <m_StatisticsNameVector>InjectedDose</m_StatisticsNameVector>
          <m_StatisticsValueVector1>250.0</m_StatisticsValueVector1>
        </root>
        """
        parsed = webui.parse_pet_dose_report(xml)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed[0]["name"], "InjectedDose")
        self.assertEqual(parsed[0]["value"], "250.0")

    def test_parse_pet_dose_report_invalid(self):
        self.assertIsNone(webui.parse_pet_dose_report(""))
        self.assertIsNone(webui.parse_pet_dose_report("<xml"))

    def test_parse_db_float(self):
        self.assertEqual(webui.parse_db_float(" 3.5 "), 3.5)
        self.assertEqual(webui.parse_db_float(2), 2.0)
        self.assertIsNone(webui.parse_db_float(""))
        self.assertIsNone(webui.parse_db_float("abc"))

    def test_get_patient_weight(self):
        self.assertEqual(webui.get_patient_weight({"patient_weight": "70"}), 70.0)
        self.assertEqual(webui.get_patient_weight({"study_patient_weight": "71"}), 71.0)
        # size fallback with kg-like value
        self.assertEqual(webui.get_patient_weight({"patient_size": "72"}), 72.0)
        self.assertIsNone(webui.get_patient_weight({"patient_size": "1.8"}))

    def test_format_export_value_bmi(self):
        # Current implementation short-circuits to empty when bmi is None.
        row = {"bmi": "derive", "patient_weight": "81", "patient_size": "1.8"}
        self.assertEqual(webui.format_export_value("bmi", row), "25.0")

    def test_format_export_value_injected_activity(self):
        row = {"injected_activity": 120000000, "injected_activity_unit": None}
        self.assertEqual(webui.format_export_value("injected_activity", row), "120.00 MBq")

    def test_format_export_value_dose_per_kg(self):
        row = {"dose_per_kg": 3.25}
        self.assertEqual(webui.format_export_value("dose_per_kg", row), "3.25 MBq/kg")

    def test_build_anonymize_fields(self):
        fields = webui.build_anonymize_fields({})
        self.assertTrue(fields)
        self.assertIn("name", fields[0])
        self.assertIn("label", fields[0])
        self.assertIn("default", fields[0])

    def test_build_export_sections_translation_and_fallback(self):
        sections, label_map = webui.build_export_sections(
            {"patient_information": "Patient Info", "patient_name": "Patient Name"}
        )
        self.assertTrue(sections)
        self.assertEqual(sections[0]["label"], "Patient Info")
        self.assertEqual(label_map["patient_name"], "Patient Name")
        # fallback when no translation key is provided
        self.assertEqual(label_map["study_id"], "Study Id")

    def test_parse_float_arg_and_decimal_places(self):
        self.assertEqual(webui.parse_float_arg(" 3.25 "), 3.25)
        self.assertIsNone(webui.parse_float_arg("abc"))
        self.assertIsNone(webui.parse_float_arg(""))
        self.assertEqual(webui.count_decimal_places("12"), 0)
        self.assertEqual(webui.count_decimal_places("12.340"), 3)
        self.assertEqual(webui.count_decimal_places(None), 0)

    def test_format_date_and_time(self):
        self.assertEqual(webui.format_date("20260301"), "01/03/2026")
        self.assertEqual(webui.format_date("bad"), "bad")
        self.assertEqual(webui.format_time("123456"), "12:34:56")
        self.assertEqual(webui.format_time("123456.789"), "12:34:56.7")
        self.assertEqual(webui.format_time("12"), "12")

    def test_parse_time_seconds_and_date_days(self):
        self.assertEqual(webui.parse_time_to_seconds("010203"), 3723)
        self.assertAlmostEqual(webui.parse_time_to_seconds("010203.5"), 3723.5, places=3)
        self.assertIsNone(webui.parse_time_to_seconds("bad"))
        self.assertEqual(webui.parse_date_to_days("19700101"), 0)
        self.assertIsNone(webui.parse_date_to_days("bad"))

    def test_calculate_patient_age_and_decay(self):
        age = webui.calculate_patient_age("20000101", "20200101")
        self.assertIsNotNone(age)
        self.assertGreater(age, 19.9)
        self.assertLess(age, 20.1)
        remaining = webui.calculate_activity_at_scan(100.0, 3600.0, 60.0)
        self.assertIsNotNone(remaining)
        self.assertLess(remaining, 100.0)
        self.assertIsNone(webui.calculate_activity_at_scan(100.0, 0, 60.0))

    def test_format_delay_ranges(self):
        self.assertEqual(webui.format_delay(30), "30.0 minutes")
        self.assertEqual(webui.format_delay(120), "2.0 hours (120 min)")
        self.assertEqual(webui.format_delay(2880), "2.0 days (2880 min)")
        self.assertIsNone(webui.format_delay(None))

    def test_compute_delay_minutes_positive_only(self):
        row = {
            "study_date": "20260301",
            "injection_time": "120000",
            "acquisition_time": "130000",
        }
        self.assertAlmostEqual(webui.compute_delay_minutes(row), 60.0, places=3)
        row_negative = {
            "study_date": "20260301",
            "injection_time": "130000",
            "acquisition_time": "120000",
        }
        self.assertIsNone(webui.compute_delay_minutes(row_negative))

    def test_format_export_value_uptake_delay(self):
        row_precomputed = {"uptake_delay": "45.0"}
        self.assertEqual(webui.format_export_value("uptake_delay", row_precomputed), "45.0")
        row_derived = {
            "uptake_delay": 0,
            "study_date": "20260301",
            "injection_time": "120000",
            "acquisition_time": "130000",
        }
        self.assertEqual(webui.format_export_value("uptake_delay", row_derived), "1.0 hours (60 min)")

    def test_resolve_db_path_and_list_databanks(self):
        with TemporaryDirectory() as td:
            temp_dir = Path(td)
            (temp_dir / "b.db").write_text("")
            (temp_dir / "a.db").write_text("")
            (temp_dir / "ignore.txt").write_text("")
            with patch.object(webui, "DATABANK_DIR", temp_dir):
                resolved = webui.resolve_db_path("mydb")
                self.assertEqual(Path(resolved), temp_dir / "mydb.db")
                self.assertEqual(webui.list_databanks(), ["a.db", "b.db"])


if __name__ == "__main__":
    unittest.main()

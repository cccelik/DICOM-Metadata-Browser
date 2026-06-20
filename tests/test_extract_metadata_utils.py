import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from dicom_browser import extract_metadata
from pydicom.dataset import Dataset
from pydicom.tag import Tag


TEST_STUDY_UID = "1.2.826.0.1.3680043.10.543.1"
TEST_SERIES_UID = "1.2.826.0.1.3680043.10.543.2"
TEST_SOP_UID = "1.2.826.0.1.3680043.10.543.3"


class Dummy:
    def __init__(self):
        self.text = "  value  "
        self.number = "42"
        self.empty = "   "


class ExtractMetadataUtilsTests(unittest.TestCase):
    def test_safe_getattr(self):
        obj = Dummy()
        self.assertEqual(extract_metadata.safe_getattr(obj, "text"), "value")
        self.assertEqual(extract_metadata.safe_getattr(obj, "number", int), 42)
        self.assertIsNone(extract_metadata.safe_getattr(obj, "missing"))
        self.assertIsNone(extract_metadata.safe_getattr(obj, "empty"))
        self.assertIsNone(extract_metadata.safe_getattr(obj, "text", int))

    def test_split_dicom_datetime(self):
        self.assertEqual(
            extract_metadata._split_dicom_datetime("20260301112233"),
            ("20260301", "112233"),
        )
        self.assertEqual(
            extract_metadata._split_dicom_datetime("2026-03-01T11:22:33"),
            ("20260301", "112233"),
        )
        self.assertEqual(extract_metadata._split_dicom_datetime("20260301"), ("20260301", None))
        self.assertEqual(extract_metadata._split_dicom_datetime("bad"), (None, None))

    def test_is_printable_ascii(self):
        self.assertTrue(extract_metadata._is_printable_ascii(b"ABC123\x00raw"))
        self.assertFalse(extract_metadata._is_printable_ascii(b"\x01\x02\x03\x04"))
        self.assertFalse(extract_metadata._is_printable_ascii(b""))

    def test_parse_numeric_and_truncate_hex(self):
        self.assertEqual(extract_metadata._parse_numeric("3.14"), 3.14)
        self.assertIsNone(extract_metadata._parse_numeric("abc"))

        raw = b"\xAA" * 10
        self.assertEqual(extract_metadata._truncate_hex(raw, max_bytes=16), raw.hex())

        long_raw = b"\xBB" * 20
        truncated = extract_metadata._truncate_hex(long_raw, max_bytes=8)
        self.assertTrue(truncated.startswith((b"\xBB" * 8).hex()))
        self.assertIn("...(len=20)", truncated)

    def test_decode_private_value_variants(self):
        class Elem:
            def __init__(self, value):
                self.value = value

        ascii_decoded = extract_metadata._decode_private_value(Elem(b"EARL\x00tail"))
        self.assertEqual(ascii_decoded["value_text"], "EARL")
        self.assertIsNotNone(ascii_decoded["value_hash"])

        binary_decoded = extract_metadata._decode_private_value(Elem(b"\x01\x02\x03"))
        self.assertIsNone(binary_decoded["value_text"])
        self.assertIsNotNone(binary_decoded["value_hex"])

        list_decoded = extract_metadata._decode_private_value(Elem(["1.5"]))
        self.assertEqual(list_decoded["value_text"], "1.5")
        self.assertEqual(list_decoded["value_num"], 1.5)

    def test_classify_private_tag(self):
        self.assertEqual(
            extract_metadata._classify_private_tag("SIEMENS CSA HEADER", "Siemens", "PT", {"value_text": "x"}),
            "vendor_semantic",
        )
        self.assertEqual(
            extract_metadata._classify_private_tag("QIICR", None, None, {"value_text": "x"}),
            "pipeline_provenance",
        )
        self.assertEqual(
            extract_metadata._classify_private_tag("VARIAN", None, None, {"value_text": "x"}),
            "rt_provenance",
        )
        self.assertEqual(
            extract_metadata._classify_private_tag("UNKNOWN", "Unknown", "CT", {"value_text": None, "value_num": None}),
            "unknown_binary",
        )

    def test_build_private_creator_map_and_extract_private_tags(self):
        ds = Dataset()
        ds.add_new(Tag(0x0029, 0x0010), "LO", "SIEMENS CSA HEADER")
        ds.add_new(Tag(0x0029, 0x1010), "LO", "EARL protocol")

        metadata = extract_metadata.DICOMMetadata(
            manufacturer="SIEMENS",
            modality="PT",
            study_instance_uid=TEST_STUDY_UID,
            series_instance_uid=TEST_SERIES_UID,
            sop_instance_uid=TEST_SOP_UID,
        )

        creator_map = extract_metadata._build_private_creator_map(ds)
        self.assertIn(0x0029, creator_map)
        self.assertEqual(creator_map[0x0029][0x0010], "SIEMENS CSA HEADER")

        tags = extract_metadata.extract_private_tags(ds, metadata)
        self.assertEqual(len(tags), 1)
        self.assertEqual(tags[0]["creator"], "SIEMENS CSA HEADER")
        self.assertEqual(tags[0]["classification"], "vendor_semantic")

    def test_extract_metadata_reads_additional_export_fields(self):
        ds = Dataset()
        ds.PatientID = "P1"
        ds.StudyInstanceUID = TEST_STUDY_UID
        ds.SeriesInstanceUID = TEST_SERIES_UID
        ds.SOPInstanceUID = TEST_SOP_UID
        ds.SoftwareVersions = "VG80B"
        ds.ReconstructionMethod = "PSF+TOF 4i5s"
        ds.Rows = 440
        ds.Columns = 512
        ds.SeriesType = ["WHOLE BODY", "IMAGE"]
        ds.AttenuationCorrectionMethod = "measured,AC"
        ds.ScatterCorrectionMethod = "Model-based"
        ds.ScatterFractionFactor = "0.472194"

        with TemporaryDirectory() as td:
            dcm_path = Path(td) / "sample.dcm"
            dcm_path.write_bytes(b"DICM")
            with patch.object(extract_metadata, "_read_dicom_dataset", return_value=ds):
                meta = extract_metadata.extract_metadata(dcm_path)

        self.assertIsNotNone(meta)
        self.assertEqual(meta.software_version, "VG80B")
        self.assertEqual(meta.reconstruction_method, "PSF+TOF 4i5s")
        self.assertEqual(meta.rows, 440)
        self.assertEqual(meta.columns, 512)
        self.assertEqual(meta.series_type, "['WHOLE BODY', 'IMAGE']")
        self.assertEqual(meta.attenuation_correction_method, "measured,AC")
        self.assertEqual(meta.scatter_correction_method, "Model-based")
        self.assertAlmostEqual(meta.scatter_fraction_factor, 0.472194, places=6)

    def test_extract_metadata_prefers_number_of_slices_over_images_in_acquisition(self):
        ds = Dataset()
        ds.PatientID = "P1"
        ds.StudyInstanceUID = TEST_STUDY_UID
        ds.SeriesInstanceUID = TEST_SERIES_UID
        ds.SOPInstanceUID = TEST_SOP_UID
        ds.NumberOfSlices = 123
        ds.ImagesInAcquisition = 456

        with TemporaryDirectory() as td:
            dcm_path = Path(td) / "sample.dcm"
            dcm_path.write_bytes(b"DICM")
            with patch.object(extract_metadata, "_read_dicom_dataset", return_value=ds):
                meta = extract_metadata.extract_metadata(dcm_path)

        self.assertIsNotNone(meta)
        self.assertEqual(meta.number_of_slices, 123)

    def test_extract_metadata_uses_partial_read_for_oversized_file(self):
        ds = Dataset()
        ds.PatientID = "P1"
        ds.StudyInstanceUID = TEST_STUDY_UID
        ds.SeriesInstanceUID = TEST_SERIES_UID
        ds.SOPInstanceUID = TEST_SOP_UID

        with TemporaryDirectory() as td:
            dcm_path = Path(td) / "large.dcm"
            dcm_path.write_bytes(b"\x00" * 128 + b"DICM" + b"x" * 100)
            with patch.object(extract_metadata, "read_partial", return_value=ds) as read_partial:
                meta = extract_metadata.extract_metadata(
                    dcm_path,
                    max_full_file_bytes=10,
                    partial_read_oversized=True,
                    partial_read_limit_bytes=32,
                )

        self.assertIsNotNone(meta)
        self.assertEqual(meta.patient_id, "P1")
        self.assertTrue(read_partial.called)
        stop_when = read_partial.call_args.kwargs["stop_when"]
        self.assertTrue(stop_when(Tag(0x7FE1, 0x1010), "OB", 90 * 1024 * 1024))

    def test_bulk_data_boundary_detects_pixel_and_large_private_raw(self):
        self.assertTrue(extract_metadata._is_bulk_data_boundary(Tag(0x7FE0, 0x0010), "OW", 1024))
        self.assertTrue(extract_metadata._is_bulk_data_boundary(Tag(0x7FE1, 0x1010), "OB", 1024))
        self.assertTrue(extract_metadata._is_bulk_data_boundary(Tag(0x0029, 0x1010), "OB", 9 * 1024 * 1024))
        self.assertFalse(extract_metadata._is_bulk_data_boundary(Tag(0x0029, 0x1010), "OB", 4096))
        self.assertFalse(extract_metadata._is_bulk_data_boundary(Tag(0x0010, 0x0010), "PN", 64))


if __name__ == "__main__":
    unittest.main()

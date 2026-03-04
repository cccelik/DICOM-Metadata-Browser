#!/usr/bin/env python3
"""
Create mock DICOM data for testing discovery and extraction flows.

Modes:
1) Single file output (any extension, including none)
2) Tree output with multiple studies/series/files and mixed extensions
"""

import argparse
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

import numpy as np
from pydicom import Dataset
from pydicom.dataset import Dataset as DSDataset
from pydicom.sequence import Sequence
from pydicom.uid import generate_uid

PET_IMAGE_STORAGE_UID = "1.2.840.10008.5.1.4.1.1.128"
TRANSFER_SYNTAX_UID = "1.2.840.10008.1.2.1"  # Explicit VR Little Endian
DEFAULT_EXTENSIONS = [".dcm", ".DCM", ".ima", ".IMA", ""]


def format_time(time_str):
    """Format DICOM time (HHMMSS) to human-readable format (HH:MM:SS)."""
    if not time_str or len(str(time_str)) < 6:
        return time_str
    try:
        text = str(time_str).strip()
        if len(text) >= 6:
            return f"{text[:2]}:{text[2:4]}:{text[4:6]}"
    except (TypeError, ValueError):
        pass
    return time_str


def _build_mock_dataset(
    *,
    patient_name: str,
    patient_id: str,
    study_uid: str,
    series_uid: str,
    study_id: str,
    series_number: int,
    acquisition_datetime: datetime,
) -> Dataset:
    ds = Dataset()

    ds.file_meta = Dataset()
    ds.file_meta.TransferSyntaxUID = TRANSFER_SYNTAX_UID
    ds.file_meta.MediaStorageSOPClassUID = PET_IMAGE_STORAGE_UID
    ds.file_meta.ImplementationClassUID = "1.2.3.4.5.6.7.8.9"
    ds.file_meta.ImplementationVersionName = "MOCK_DICOM_2.0"

    ds.PatientName = patient_name
    ds.PatientID = patient_id
    ds.PatientBirthDate = "19800101"
    ds.PatientSex = "M"
    ds.PatientAge = "044Y"
    ds.PatientWeight = 75.5
    ds.PatientSize = 1.80

    ds.StudyInstanceUID = study_uid
    ds.StudyDate = acquisition_datetime.strftime("%Y%m%d")
    ds.StudyTime = acquisition_datetime.strftime("%H%M%S")
    ds.StudyDescription = "Mock Test Study"
    ds.StudyID = study_id
    ds.AccessionNumber = f"ACC{study_id}"

    ds.SeriesInstanceUID = series_uid
    ds.SeriesNumber = series_number
    ds.SeriesDate = acquisition_datetime.strftime("%Y%m%d")
    ds.SeriesTime = acquisition_datetime.strftime("%H%M%S")
    ds.SeriesDescription = f"Mock Series {series_number:02d}"
    ds.Modality = "NM"

    sop_uid = generate_uid()
    ds.SOPInstanceUID = sop_uid
    ds.SOPClassUID = PET_IMAGE_STORAGE_UID
    ds.file_meta.MediaStorageSOPInstanceUID = sop_uid

    ds.AcquisitionDate = acquisition_datetime.strftime("%Y%m%d")
    ds.AcquisitionTime = acquisition_datetime.strftime("%H%M%S")

    injection_datetime = acquisition_datetime - timedelta(hours=1)
    injection_time_str = injection_datetime.strftime("%H%M%S")
    injection_date_str = injection_datetime.strftime("%Y%m%d")

    rad_info_item = DSDataset()
    rad_info_item.Radiopharmaceutical = "FDG"
    rad_info_item.RadionuclideTotalDose = 250.0
    rad_info_item.RadiopharmaceuticalStartTime = injection_time_str
    rad_info_item.RadiopharmaceuticalStartDateTime = injection_datetime.strftime("%Y%m%d%H%M%S")
    rad_info_item.RadionuclideHalfLife = 6586.2
    rad_info_item.RadiopharmaceuticalVolume = 5.0
    ds.RadiopharmaceuticalInformationSequence = Sequence([rad_info_item])
    ds.DecayCorrection = "START"

    ds.Manufacturer = "Mock Manufacturer"
    ds.ManufacturerModelName = "Mock Scanner Model"
    ds.StationName = "MOCK_STATION_01"
    ds.SoftwareVersions = ["1.0.0"]
    ds.DeviceSerialNumber = "MOCK12345"
    ds.InstitutionName = "Mock Institution"

    ds.Rows = 256
    ds.Columns = 256
    ds.BitsAllocated = 16
    ds.BitsStored = 12
    ds.HighBit = 11
    ds.PixelSpacing = [2.0, 2.0]
    ds.SliceThickness = 3.0
    ds.SpacingBetweenSlices = 3.0
    ds.PixelData = np.zeros((256, 256), dtype=np.uint16).tobytes()
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"

    ds.is_little_endian = True
    ds.is_implicit_VR = False
    return ds


def _write_dataset(ds: Dataset, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ds.save_as(str(output_path), write_like_original=False)


def create_mock_dicom(patient_name="Max Musterman", output_path="mock_dicom.dcm") -> Dataset:
    """Create one mock DICOM file (extension can be any string or none)."""
    output = Path(output_path)
    now = datetime.now()
    ds = _build_mock_dataset(
        patient_name=patient_name,
        patient_id="TEST123456",
        study_uid=generate_uid(),
        series_uid=generate_uid(),
        study_id="STUDY001",
        series_number=1,
        acquisition_datetime=now,
    )
    _write_dataset(ds, output)

    print(f"✓ Created mock DICOM file: {output}")
    print(f"  Patient Name: {patient_name}")
    print(f"  Patient ID: {ds.PatientID}")
    print(f"  Study Date: {ds.StudyDate}")
    print(f"  Modality: {ds.Modality}")
    print(f"  Acquisition Time: {ds.AcquisitionTime} ({format_time(ds.AcquisitionTime)})")
    return ds


def create_mock_tree(
    output_root: Path,
    *,
    patient_name: str,
    studies: int,
    series_per_study: int,
    files_per_series: int,
    include_junk: bool,
) -> List[Path]:
    """Create a multi-study/series tree with mixed DICOM filename extensions."""
    created_files: List[Path] = []
    now = datetime.now()

    for study_idx in range(1, studies + 1):
        study_dir = output_root / f"Study_{study_idx:02d}"
        study_uid = generate_uid()
        study_id = f"STUDY{study_idx:03d}"
        patient_id = f"TEST{study_idx:06d}"

        for series_idx in range(1, series_per_study + 1):
            series_dir = study_dir / f"Series_{series_idx:02d}"
            series_uid = generate_uid()
            # Keep one extension style per series directory so each series is homogeneous.
            series_extension = DEFAULT_EXTENSIONS[(series_idx - 1) % len(DEFAULT_EXTENSIONS)]

            for file_idx in range(1, files_per_series + 1):
                filename = f"IMG_{file_idx:04d}{series_extension}"
                acq_dt = now + timedelta(minutes=(study_idx * 20 + series_idx * 5 + file_idx))
                ds = _build_mock_dataset(
                    patient_name=patient_name,
                    patient_id=patient_id,
                    study_uid=study_uid,
                    series_uid=series_uid,
                    study_id=study_id,
                    series_number=series_idx,
                    acquisition_datetime=acq_dt,
                )
                out_path = series_dir / filename
                _write_dataset(ds, out_path)
                created_files.append(out_path)

            if include_junk:
                (series_dir / "notes.txt").write_text("not a dicom\n", encoding="utf-8")
                (series_dir / ".DS_Store").write_bytes(b"\x00\x01mock")

    return created_files


def create_dashboard_demo_tree(
    output_root: Path,
    *,
    patients: int,
    include_junk: bool,
) -> List[Path]:
    """Create a dashboard-focused mock dataset with intentionally varied QA patterns.

    The generated data is designed to exercise dashboard features:
    - plausible and implausible uptake delays
    - missing injection times
    - missing injected activity / radiopharmaceutical
    - wide dose-per-kg spread
    - mixed file extensions (including extensionless files)
    """
    created_files: List[Path] = []
    base_time = datetime.now().replace(second=0, microsecond=0)
    weights = [45.0, 52.0, 60.0, 68.0, 75.0, 83.0, 92.0, 105.0]

    # (delay_minutes, dose_per_kg_mbq, rad_name)
    # dose_per_kg=None => missing injected activity
    # delay_minutes=None => missing injection time/date
    scenarios = [
        (45, 2.5, "FDG"),       # plausible
        (60, 3.5, "FDG"),       # plausible
        (90, 4.2, "F-18 FLT"),  # plausible higher delay
        (15, 1.0, "FDG"),       # low dose per kg
        (30, 7.5, "Ga-68 PSMA"),  # high dose per kg
        (240, 4.0, "FDG"),      # implausibly high delay
        (480, 2.8, "C-11 Choline"),  # very high delay
        (-20, 3.2, "FDG"),      # negative delay
        (None, 3.0, "FDG"),     # missing injection time/date
        (75, None, "F-18 NaF"),  # missing injected activity
        (55, 2.7, None),        # missing radiopharmaceutical name
        (5, 12.0, "Ga-68 DOTATATE"),  # extreme high dose per kg
    ]
    modalities = ["PT", "CT", "NM"]
    manufacturers = [
        "Siemens",
        "GE MEDICAL SYSTEMS",
        "Philips",
        "Canon Medical Systems",
    ]
    scanner_models = [
        "Biograph mCT",
        "Discovery MI",
        "Vereos",
        "Aquilion ONE",
    ]

    for patient_idx in range(1, patients + 1):
        scenario = scenarios[(patient_idx - 1) % len(scenarios)]
        delay_minutes, dose_per_kg, rad_name = scenario
        weight = weights[(patient_idx - 1) % len(weights)]
        modality = modalities[(patient_idx - 1) % len(modalities)]
        manufacturer = manufacturers[(patient_idx - 1) % len(manufacturers)]
        model = scanner_models[(patient_idx - 1) % len(scanner_models)]

        patient_name = f"Mock Patient {patient_idx}"
        patient_id = f"MOCK{patient_idx:06d}"
        study_uid = generate_uid()
        series_uid = generate_uid()
        study_id = f"DASH{patient_idx:04d}"

        study_dir = output_root / f"Patient_{patient_idx:03d}"
        series_dir = study_dir / "Series_01"

        extension = DEFAULT_EXTENSIONS[(patient_idx - 1) % len(DEFAULT_EXTENSIONS)]
        filename = f"IMG_0001{extension}"
        acq_dt = base_time + timedelta(minutes=patient_idx * 7)

        ds = _build_mock_dataset(
            patient_name=patient_name,
            patient_id=patient_id,
            study_uid=study_uid,
            series_uid=series_uid,
            study_id=study_id,
            series_number=1,
            acquisition_datetime=acq_dt,
        )
        ds.Modality = modality
        ds.Manufacturer = manufacturer
        ds.ManufacturerModelName = model

        # overwrite patient-specific weight for dose-per-kg variability
        ds.PatientWeight = float(weight)

        is_tracer_modality = modality in {"PT", "NM"}
        if is_tracer_modality:
            # Set or remove radiopharmaceutical activity context for PT/NM.
            if dose_per_kg is None:
                if "RadiopharmaceuticalInformationSequence" in ds and len(ds.RadiopharmaceuticalInformationSequence) > 0:
                    item = ds.RadiopharmaceuticalInformationSequence[0]
                    if hasattr(item, "RadionuclideTotalDose"):
                        del item.RadionuclideTotalDose
            else:
                injected_activity = float(dose_per_kg * weight)  # MBq-scale value
                if "RadiopharmaceuticalInformationSequence" in ds and len(ds.RadiopharmaceuticalInformationSequence) > 0:
                    item = ds.RadiopharmaceuticalInformationSequence[0]
                    item.RadionuclideTotalDose = injected_activity

            if "RadiopharmaceuticalInformationSequence" in ds and len(ds.RadiopharmaceuticalInformationSequence) > 0:
                item = ds.RadiopharmaceuticalInformationSequence[0]
                if rad_name is None:
                    if hasattr(item, "Radiopharmaceutical"):
                        del item.Radiopharmaceutical
                else:
                    item.Radiopharmaceutical = rad_name

            # Set or remove temporal context to create varied delay behavior.
            if delay_minutes is None:
                if "RadiopharmaceuticalInformationSequence" in ds and len(ds.RadiopharmaceuticalInformationSequence) > 0:
                    item = ds.RadiopharmaceuticalInformationSequence[0]
                    if hasattr(item, "RadiopharmaceuticalStartTime"):
                        del item.RadiopharmaceuticalStartTime
                    if hasattr(item, "RadiopharmaceuticalStartDateTime"):
                        del item.RadiopharmaceuticalStartDateTime
            else:
                inj_dt = acq_dt - timedelta(minutes=delay_minutes)
                inj_time_str = inj_dt.strftime("%H%M%S")
                if "RadiopharmaceuticalInformationSequence" in ds and len(ds.RadiopharmaceuticalInformationSequence) > 0:
                    item = ds.RadiopharmaceuticalInformationSequence[0]
                    item.RadiopharmaceuticalStartTime = inj_time_str
                    item.RadiopharmaceuticalStartDateTime = inj_dt.strftime("%Y%m%d%H%M%S")
        else:
            # CT should not contain injected radiopharmaceutical context in this demo.
            if hasattr(ds, "RadiopharmaceuticalInformationSequence"):
                del ds.RadiopharmaceuticalInformationSequence
            ds.DecayCorrection = "NONE"

        out_path = series_dir / filename
        _write_dataset(ds, out_path)
        created_files.append(out_path)

        if include_junk:
            (series_dir / "notes.txt").write_text("dashboard demo non-dicom\n", encoding="utf-8")
            (series_dir / ".DS_Store").write_bytes(b"\x00\x01mock")

    return created_files


def main() -> None:
    parser = argparse.ArgumentParser(description="Create mock DICOM test data.")
    parser.add_argument(
        "output",
        nargs="?",
        default="mock_max_musterman.dcm",
        help="Single-file output path, or output root in --tree mode.",
    )
    parser.add_argument(
        "--patient-name",
        default="Max Musterman",
        help="Patient name used in generated files.",
    )
    parser.add_argument(
        "--tree",
        action="store_true",
        help="Generate a multi-study/series directory tree with mixed extensions.",
    )
    parser.add_argument("--studies", type=int, default=2, help="Number of study directories in --tree mode.")
    parser.add_argument(
        "--series-per-study",
        type=int,
        default=3,
        help="Number of series directories per study in --tree mode.",
    )
    parser.add_argument(
        "--files-per-series",
        type=int,
        default=5,
        help="Number of DICOM files per series in --tree mode.",
    )
    parser.add_argument(
        "--no-junk",
        action="store_true",
        help="Do not create non-DICOM junk files in each series directory.",
    )
    parser.add_argument(
        "--dashboard-demo",
        action="store_true",
        help="Generate patient-wise mock data for dashboard QA demonstration.",
    )
    parser.add_argument(
        "--patients",
        type=int,
        default=60,
        help="Number of patients for --dashboard-demo mode.",
    )
    args = parser.parse_args()

    if args.dashboard_demo:
        output_root = Path(args.output).resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        created = create_dashboard_demo_tree(
            output_root,
            patients=max(1, args.patients),
            include_junk=not args.no_junk,
        )
        print(f"✓ Created dashboard demo tree in: {output_root}")
        print(f"  Patients created: {max(1, args.patients)}")
        print(f"  DICOM files created: {len(created)}")
        print(f"  Example file: {created[0] if created else 'none'}")
        print()
        print("Try:")
        print(f"  python3 process_dicom.py {output_root} mock_dashboard_demo.db --no-subdirs")
        return

    if args.tree:
        output_root = Path(args.output).resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        created = create_mock_tree(
            output_root,
            patient_name=args.patient_name,
            studies=max(1, args.studies),
            series_per_study=max(1, args.series_per_study),
            files_per_series=max(1, args.files_per_series),
            include_junk=not args.no_junk,
        )
        print(f"✓ Created test tree in: {output_root}")
        print(f"  DICOM files created: {len(created)}")
        print(f"  Example file: {created[0] if created else 'none'}")
        print()
        print("Try:")
        print(f"  python3 process_dicom.py {output_root} mock_tree.db")
        print(f"  python3 extract_one_per_series.py {output_root} {output_root}_samples")
        return

    output_path = Path(args.output).resolve()
    create_mock_dicom(patient_name=args.patient_name, output_path=str(output_path))
    print(f"\nFile saved to: {output_path}")
    print("\nYou can test it with:")
    if output_path.suffix:
        print(f"  python3 process_dicom.py {output_path}")
    else:
        print(f"  python3 process_dicom.py {output_path}")


if __name__ == "__main__":
    main()

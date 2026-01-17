#!/usr/bin/env python3
"""
Simple DICOM Metadata Extractor
Extracts all important medical and manufacturer metadata from DICOM files.
"""

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pydicom  # type: ignore[import]

@dataclass
class DICOMMetadata:
    """Container for all extracted DICOM metadata"""
    
    # Patient Information
    patient_id: Optional[str] = None
    patient_name: Optional[str] = None
    patient_birth_date: Optional[str] = None
    patient_sex: Optional[str] = None
    patient_age: Optional[str] = None
    patient_weight: Optional[float] = None
    patient_size: Optional[float] = None  # Height in meters (0010,1020)
    
    # Study Information
    study_instance_uid: Optional[str] = None
    study_date: Optional[str] = None
    study_time: Optional[str] = None
    study_description: Optional[str] = None
    study_id: Optional[str] = None
    accession_number: Optional[str] = None
    referring_physician_name: Optional[str] = None
    
    # Series Information
    series_instance_uid: Optional[str] = None
    series_number: Optional[int] = None
    series_date: Optional[str] = None
    series_time: Optional[str] = None
    series_description: Optional[str] = None
    protocol_name: Optional[str] = None
    modality: Optional[str] = None
    body_part_examined: Optional[str] = None
    
    # Manufacturer Information
    manufacturer: Optional[str] = None
    manufacturer_model_name: Optional[str] = None
    station_name: Optional[str] = None
    software_version: Optional[str] = None
    device_serial_number: Optional[str] = None
    institution_name: Optional[str] = None
    institution_address: Optional[str] = None
    
    # Acquisition Information
    acquisition_date: Optional[str] = None
    acquisition_time: Optional[str] = None
    patient_position: Optional[str] = None
    scanning_sequence: Optional[str] = None
    sequence_variant: Optional[str] = None
    scan_options: Optional[str] = None
    acquisition_type: Optional[str] = None
    slice_thickness: Optional[float] = None
    reconstruction_diameter: Optional[float] = None
    reconstruction_algorithm: Optional[str] = None
    convolution_kernel: Optional[str] = None
    filter_type: Optional[str] = None
    spiral_pitch_factor: Optional[float] = None
    ctdivol: Optional[float] = None
    dlp: Optional[float] = None
    kvp: Optional[float] = None
    exposure_time: Optional[float] = None
    exposure: Optional[float] = None
    tube_current: Optional[float] = None
    
    # Nuclear Medicine Specific
    radiopharmaceutical: Optional[str] = None
    injected_activity: Optional[float] = None
    injected_activity_unit: Optional[str] = None
    injection_time: Optional[str] = None
    injection_date: Optional[str] = None
    half_life: Optional[float] = None
    decay_correction: Optional[str] = None
    
    # Additional Radiopharmaceutical Information
    radiopharmaceutical_volume: Optional[float] = None  # (0018,1071)
    radionuclide_total_dose: Optional[float] = None  # (0018,1074)
    
    # Image Information
    image_type: Optional[str] = None
    pixel_spacing: Optional[str] = None
    image_orientation_patient: Optional[str] = None
    slice_location: Optional[float] = None
    number_of_frames: Optional[int] = None
    frame_time: Optional[float] = None
    number_of_slices: Optional[int] = None

    # Private (CTP anonymizer) metadata
    ctp_collection: Optional[str] = None
    ctp_subject_id: Optional[str] = None
    ctp_private_flag_raw: Optional[str] = None
    ctp_private_flag_int: Optional[int] = None
    
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)


def safe_getattr(obj, attr: str, cast_type=None):
    """Safely get attribute from DICOM dataset"""
    try:
        value = getattr(obj, attr, None)
        if value is None:
            return None
        
        # Convert PersonName and other DICOM types to string
        if hasattr(value, '__str__'):
            value = str(value)
        
        # Strip whitespace from strings
        if isinstance(value, str):
            value = value.strip()
            if not value or value == '':
                return None
        
        # Cast to requested type
        if cast_type and value is not None:
            try:
                return cast_type(value)
            except (ValueError, TypeError):
                return None
        
        return value
    except Exception:
        return None


def extract_metadata(dcm_path: Path) -> Optional[DICOMMetadata]:
    """Extract all important metadata from a DICOM file"""
    # Skip macOS metadata files
    if dcm_path.name.startswith('._') or '__MACOSX' in str(dcm_path):
        return None
    
    try:
        ds = pydicom.dcmread(dcm_path, stop_before_pixels=True, force=False)
    except Exception as e:
        # Silently skip files that can't be read (macOS metadata, invalid DICOM, etc.)
        return None
    
    meta = DICOMMetadata()
    
    # Patient Information
    meta.patient_id = safe_getattr(ds, 'PatientID')
    meta.patient_name = safe_getattr(ds, 'PatientName')
    meta.patient_birth_date = safe_getattr(ds, 'PatientBirthDate')
    meta.patient_sex = safe_getattr(ds, 'PatientSex')
    meta.patient_age = safe_getattr(ds, 'PatientAge')
    meta.patient_weight = safe_getattr(ds, 'PatientWeight', float)
    meta.patient_size = safe_getattr(ds, 'PatientSize', float)  # Height in meters
    
    # Study Information
    meta.study_instance_uid = safe_getattr(ds, 'StudyInstanceUID')
    meta.study_date = safe_getattr(ds, 'StudyDate')
    meta.study_time = safe_getattr(ds, 'StudyTime')
    meta.study_description = safe_getattr(ds, 'StudyDescription')
    meta.study_id = safe_getattr(ds, 'StudyID')
    meta.accession_number = safe_getattr(ds, 'AccessionNumber')
    meta.referring_physician_name = safe_getattr(ds, 'ReferringPhysicianName')
    
    # Series Information
    meta.series_instance_uid = safe_getattr(ds, 'SeriesInstanceUID')
    meta.series_number = safe_getattr(ds, 'SeriesNumber', int)
    meta.series_date = safe_getattr(ds, 'SeriesDate')
    meta.series_time = safe_getattr(ds, 'SeriesTime')
    meta.series_description = safe_getattr(ds, 'SeriesDescription')
    meta.protocol_name = safe_getattr(ds, 'ProtocolName')
    meta.modality = safe_getattr(ds, 'Modality')
    meta.body_part_examined = safe_getattr(ds, 'BodyPartExamined')
    
    # Manufacturer Information
    meta.manufacturer = safe_getattr(ds, 'Manufacturer')
    meta.manufacturer_model_name = safe_getattr(ds, 'ManufacturerModelName')
    meta.station_name = safe_getattr(ds, 'StationName')
    meta.software_version = safe_getattr(ds, 'SoftwareVersion')
    meta.device_serial_number = safe_getattr(ds, 'DeviceSerialNumber')
    meta.institution_name = safe_getattr(ds, 'InstitutionName')
    meta.institution_address = safe_getattr(ds, 'InstitutionAddress')
    
    # Acquisition Information
    meta.acquisition_date = safe_getattr(ds, 'AcquisitionDate')
    meta.acquisition_time = safe_getattr(ds, 'AcquisitionTime')
    meta.patient_position = safe_getattr(ds, 'PatientPosition')
    meta.scanning_sequence = safe_getattr(ds, 'ScanningSequence')
    meta.sequence_variant = safe_getattr(ds, 'SequenceVariant')
    meta.scan_options = safe_getattr(ds, 'ScanOptions')
    meta.acquisition_type = safe_getattr(ds, 'AcquisitionType')
    meta.slice_thickness = safe_getattr(ds, 'SliceThickness', float)
    meta.reconstruction_diameter = safe_getattr(ds, 'ReconstructionDiameter', float)
    meta.reconstruction_algorithm = safe_getattr(ds, 'ReconstructionAlgorithm')
    meta.convolution_kernel = safe_getattr(ds, 'ConvolutionKernel')
    meta.filter_type = safe_getattr(ds, 'FilterType')
    meta.spiral_pitch_factor = safe_getattr(ds, 'SpiralPitchFactor', float)
    meta.ctdivol = safe_getattr(ds, 'CTDIvol', float)
    meta.dlp = safe_getattr(ds, 'DLP', float)
    meta.kvp = safe_getattr(ds, 'KVP', float)
    meta.exposure_time = safe_getattr(ds, 'ExposureTime', float)
    meta.exposure = safe_getattr(ds, 'Exposure', float)
    meta.tube_current = safe_getattr(ds, 'TubeCurrent', float)
    
    # Nuclear Medicine Specific
    if 'RadiopharmaceuticalInformationSequence' in ds:
        try:
            rad_seq = ds.RadiopharmaceuticalInformationSequence
            if len(rad_seq) > 0:
                item = rad_seq[0]
                meta.radiopharmaceutical = safe_getattr(item, 'Radiopharmaceutical')
                meta.injected_activity = safe_getattr(item, 'RadionuclideTotalDose', float)
                meta.injection_time = safe_getattr(item, 'RadiopharmaceuticalStartTime')
                meta.half_life = safe_getattr(item, 'RadionuclideHalfLife', float)
                # Additional radiopharmaceutical fields from sequence
                meta.radiopharmaceutical_volume = safe_getattr(item, 'RadiopharmaceuticalVolume', float)
                meta.radionuclide_total_dose = safe_getattr(item, 'RadionuclideTotalDose', float)
        except Exception:
            pass
    
    # Fallback to direct tag access if sequence not available
    meta.radiopharmaceutical = meta.radiopharmaceutical or safe_getattr(ds, 'Radiopharmaceutical')
    meta.injection_time = meta.injection_time or safe_getattr(ds, 'InjectionTime')
    meta.injection_date = safe_getattr(ds, 'InjectionDate')
    meta.half_life = meta.half_life or safe_getattr(ds, 'HalfLife', float)
    meta.decay_correction = safe_getattr(ds, 'DecayCorrection')
    
    # Extract additional radiopharmaceutical tags directly (0018,1071, 0018,1074)
    meta.radiopharmaceutical_volume = meta.radiopharmaceutical_volume or safe_getattr(ds, 'RadiopharmaceuticalVolume', float)
    meta.radionuclide_total_dose = meta.radionuclide_total_dose or safe_getattr(ds, 'RadionuclideTotalDose', float)
    
    # Use radionuclide_total_dose as injected_activity if not already set
    if not meta.injected_activity and meta.radionuclide_total_dose:
        meta.injected_activity = meta.radionuclide_total_dose
    
    # Image Information
    meta.image_type = safe_getattr(ds, 'ImageType')
    meta.pixel_spacing = safe_getattr(ds, 'PixelSpacing')
    meta.image_orientation_patient = safe_getattr(ds, 'ImageOrientationPatient')
    meta.slice_location = safe_getattr(ds, 'SliceLocation', float)
    meta.number_of_frames = safe_getattr(ds, 'NumberOfFrames', int)
    meta.frame_time = safe_getattr(ds, 'FrameTime', float)
    meta.number_of_slices = safe_getattr(ds, 'ImagesInAcquisition', int) or meta.number_of_frames

    def _get_ctp_value(element_offset: int):
        try:
            block = ds.private_block(0x0013, "CTP", create=False)
            if block is not None:
                tag = block.get_tag(element_offset)
                if tag in ds:
                    return ds[tag].value
        except Exception:
            pass
        try:
            elem = ds.get((0x0013, 0x1000 + element_offset))
            if elem is not None:
                return elem.value
        except Exception:
            pass
        return None

    ctp_collection = _get_ctp_value(0x10)
    if ctp_collection is not None:
        collection_str = str(ctp_collection).strip()
        if collection_str:
            meta.ctp_collection = collection_str

    ctp_subject_id = _get_ctp_value(0x13)
    if ctp_subject_id is not None:
        subject_str = str(ctp_subject_id).strip()
        if subject_str:
            meta.ctp_subject_id = subject_str

    ctp_flag = _get_ctp_value(0x15)
    if ctp_flag is not None:
        if isinstance(ctp_flag, (bytes, bytearray)):
            meta.ctp_private_flag_raw = ctp_flag.hex()
            if len(ctp_flag) in (1, 2, 4, 8):
                meta.ctp_private_flag_int = int.from_bytes(ctp_flag, byteorder="little", signed=False)
        else:
            flag_str = str(ctp_flag).strip()
            if flag_str:
                meta.ctp_private_flag_raw = flag_str

    return meta


def extract_metadata_from_paths(
    dcm_paths: List[Path],
    max_workers: Optional[int] = None,
) -> List[Tuple[Path, DICOMMetadata]]:
    """Extract metadata for a list of DICOM files using a process pool."""
    filtered_paths = [
        dcm_path
        for dcm_path in dcm_paths
        if not (dcm_path.name.startswith("._") or "__MACOSX" in str(dcm_path))
    ]

    if not filtered_paths:
        return []

    default_workers = min(32, max(len(filtered_paths), 1))
    workers = max_workers or default_workers

    metadata_list: List[Tuple[Path, DICOMMetadata]] = []

    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(extract_metadata, path): path for path in filtered_paths}

        for future in as_completed(futures):
            dcm_path = futures[future]
            meta = future.result()
            if meta:
                metadata_list.append((dcm_path, meta))

    return metadata_list


def extract_all_metadata(
    directory: Path,
    max_workers: Optional[int] = None,
) -> List[Tuple[Path, DICOMMetadata]]:
    """Extract metadata from all DICOM files in a directory using a process pool."""
    dcm_files = list(directory.rglob("*.dcm"))
    return extract_metadata_from_paths(
        dcm_files,
        max_workers=max_workers,
    )


def _dump_metadata(metadata: List[Tuple[Path, DICOMMetadata]], output_path: Optional[Path]) -> None:
    """Serialize metadata list to stdout or a file."""
    serializable: List[Dict[str, Any]] = []
    for path_item, item in metadata:
        payload = item.to_dict()
        payload["file_path"] = str(path_item)
        serializable.append(payload)

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as fh:
            json.dump(serializable, fh, indent=2)
        print(f"Wrote metadata for {len(serializable)} DICOM file(s) to {output_path}")
    else:
        json.dump(serializable, sys.stdout, indent=2)
        sys.stdout.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract metadata from DICOM files in a directory."
    )
    parser.add_argument(
        "directory",
        type=Path,
        help="Directory (or archive root) containing DICOM files.",
    )
    parser.add_argument(
        "-m",
        "--max-workers",
        type=int,
        default=None,
        help="Maximum number of workers to use (defaults to min(32, files)).",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Optional path to write JSON metadata. Defaults to stdout.",
    )
    parser.add_argument(
        "-t",
        "--timing",
        action="store_true",
        help="Print timing information for the extraction run.",
    )

    args = parser.parse_args()

    if args.max_workers is not None and args.max_workers < 1:
        parser.error("--max-workers must be greater than zero")

    start = time.perf_counter() if args.timing else None
    metadata = extract_all_metadata(
        args.directory,
        max_workers=args.max_workers,
    )
    if args.timing and start is not None:
        elapsed = time.perf_counter() - start
        print(f"Processed {len(metadata)} DICOM file(s) in {elapsed:.2f}s")
    _dump_metadata(metadata, args.output)


if __name__ == "__main__":
    main()

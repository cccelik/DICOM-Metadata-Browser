#!/usr/bin/env python3
"""
Simple DICOM Metadata Extractor
Extracts all important medical and manufacturer metadata from DICOM files.
"""

import argparse
import hashlib
import json
import sys
import time
import struct
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
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

    # Siemens CSA headers (decoded JSON)
    csa_image_header_json: Optional[str] = None
    csa_series_header_json: Optional[str] = None
    csa_image_header_hash: Optional[str] = None
    csa_series_header_hash: Optional[str] = None
    private_payload_fingerprint: Optional[str] = None

    # SOP Instance UID (for private tag linkage)
    sop_instance_uid: Optional[str] = None

    # Private tag payloads (stored separately)
    private_tags: List[Dict[str, Any]] = field(default_factory=list)
    
    
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


def _is_printable_ascii(raw: bytes, min_ratio: float = 0.90) -> bool:
    if not raw:
        return False
    head = raw.split(b"\x00", 1)[0]
    if not head:
        return False
    printable = 0
    for b in head:
        if b in (9, 10, 13) or (32 <= b <= 126):
            printable += 1
    return printable / len(head) >= min_ratio


def _parse_numeric(text: str) -> Optional[float]:
    try:
        return float(text)
    except Exception:
        return None


def _truncate_hex(raw: bytes, max_bytes: int = 256) -> str:
    if len(raw) <= max_bytes:
        return raw.hex()
    return raw[:max_bytes].hex() + f"...(len={len(raw)})"


def _build_private_creator_map(ds: pydicom.Dataset) -> Dict[int, Dict[int, str]]:
    creators: Dict[int, Dict[int, str]] = {}
    for elem in ds.iterall():
        if not elem.tag.is_private_creator:
            continue
        group = elem.tag.group
        block = elem.tag.element
        creator = str(elem.value).strip() if elem.value is not None else ""
        if not creator:
            continue
        creators.setdefault(group, {})[block] = creator
    return creators


def _decode_private_value(elem: pydicom.DataElement) -> Dict[str, Any]:
    value_text = None
    value_num = None
    value_json = None
    value_hex = None
    byte_len = None
    value_hash = None

    value = elem.value
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
        byte_len = len(raw)
        value_hash = hashlib.sha256(raw).hexdigest()
        if raw and _is_printable_ascii(raw):
            head = raw.split(b"\x00", 1)[0]
            decoded = head.decode("latin-1", errors="ignore").strip()
            if decoded:
                value_text = decoded
                value_num = _parse_numeric(decoded)
        else:
            value_hex = _truncate_hex(raw)
    elif isinstance(value, (list, tuple)):
        text_items = [str(v) for v in value if v is not None]
        if text_items:
            value_text = ", ".join(text_items)
        if len(value) == 1:
            value_num = _parse_numeric(str(value[0]))
        value_hash = hashlib.sha256((value_text or "").encode("utf-8")).hexdigest()
    else:
        if value is not None:
            value_text = str(value).strip()
            if value_text:
                value_num = _parse_numeric(value_text)
        value_hash = hashlib.sha256((value_text or "").encode("utf-8")).hexdigest()

    return {
        "value_text": value_text,
        "value_num": value_num,
        "value_json": value_json,
        "value_hex": value_hex,
        "byte_len": byte_len,
        "value_hash": value_hash,
    }


def _classify_private_tag(creator: str, manufacturer: Optional[str], modality: Optional[str], decoded: Dict[str, Any]) -> str:
    creator_upper = (creator or "").upper()
    manufacturer_upper = (manufacturer or "").upper()
    if "CTP" in creator_upper or "QIICR" in creator_upper or "HIGHDICOM" in creator_upper:
        return "pipeline_provenance"
    if "VARIAN" in creator_upper:
        return "rt_provenance"
    if "SIEMENS" in creator_upper or "SIEMENS" in manufacturer_upper:
        if "CSA" in creator_upper:
            return "vendor_semantic"
        return "vendor_raw"
    if creator_upper in ("SD", "SPECTRUM DYNAMICS", "SPECTRUM-DYNAMICS") or "SPECTRUM" in manufacturer_upper:
        return "vendor_semantic"
    if "GE" in creator_upper or "GEMS" in creator_upper or "GE" in manufacturer_upper:
        return "vendor_raw"
    if "PHILIPS" in creator_upper or "PHILIPS" in manufacturer_upper:
        return "vendor_raw"
    if "TOSHIBA" in creator_upper or "CANON" in manufacturer_upper:
        return "vendor_raw"
    if decoded.get("value_text") or decoded.get("value_num") is not None:
        return "vendor_raw"
    return "unknown_binary"


def extract_private_tags(ds: pydicom.Dataset, metadata: DICOMMetadata) -> List[Dict[str, Any]]:
    creators = _build_private_creator_map(ds)
    results: List[Dict[str, Any]] = []
    for elem in ds.iterall():
        if not elem.tag.is_private:
            continue
        if elem.tag.is_private_creator:
            continue
        if elem.tag.element < 0x1000:
            continue
        group = elem.tag.group
        block = (elem.tag.element >> 8) & 0xFF
        creator = creators.get(group, {}).get(block, "Unknown")
        decoded = _decode_private_value(elem)
        classification = _classify_private_tag(
            creator,
            metadata.manufacturer,
            metadata.modality,
            decoded
        )
        results.append({
            "group_hex": f"{group:04X}",
            "element_hex": f"{elem.tag.element:04X}",
            "creator": creator,
            "vr": elem.VR,
            "value_text": decoded.get("value_text"),
            "value_num": decoded.get("value_num"),
            "value_json": decoded.get("value_json"),
            "value_hex": decoded.get("value_hex"),
            "byte_len": decoded.get("byte_len"),
            "value_hash": decoded.get("value_hash"),
            "classification": classification,
            "sop_instance_uid": metadata.sop_instance_uid,
        })
    return results


def _read_uint32(data: memoryview, offset: int) -> Optional[int]:
    if offset + 4 > len(data):
        return None
    return struct.unpack_from("<I", data, offset)[0]


def _read_csa_string(data: memoryview, offset: int, length: int) -> str:
    if offset + length > len(data):
        return ""
    raw = bytes(data[offset:offset + length])
    raw = raw.split(b"\x00", 1)[0]
    return raw.decode("latin-1", errors="ignore").strip()


def _align_4(offset: int) -> int:
    return (offset + 3) & ~3


def parse_csa_header(raw: bytes) -> Optional[Dict[str, Any]]:
    """Parse Siemens CSA header bytes into a JSON-serializable dict."""
    if not raw:
        return None
    data = memoryview(raw)
    fmt = "CSA1"
    offset = 0
    if raw.startswith(b"SV10"):
        fmt = "CSA2"
        offset = 8
        num_elements = _read_uint32(data, offset)
        offset = 16
    else:
        num_elements = _read_uint32(data, 0)
        offset = 8
        if num_elements is None or num_elements > 10000:
            num_elements = _read_uint32(data, 4)
            offset = 8

    if num_elements is None or num_elements <= 0:
        return None

    max_elements = min(num_elements, 2048)
    elements: Dict[str, Any] = {}

    for _ in range(max_elements):
        if offset + 84 > len(data):
            break
        name = _read_csa_string(data, offset, 64)
        offset += 64
        vm = _read_uint32(data, offset)
        offset += 4
        vr = _read_csa_string(data, offset, 4)
        offset += 4
        _syngo_dt = _read_uint32(data, offset)
        offset += 4
        nitems = _read_uint32(data, offset)
        offset += 4
        _unknown = _read_uint32(data, offset)
        offset += 4

        if nitems is None or nitems < 0:
            break

        values: List[str] = []
        for _ in range(min(nitems, 512)):
            if offset + 8 > len(data):
                break
            item_length = _read_uint32(data, offset)
            offset += 4
            _item_delim = _read_uint32(data, offset)
            offset += 4
            if item_length is None or item_length < 0:
                break
            if offset + item_length > len(data):
                break
            if item_length > 0:
                raw_value = bytes(data[offset:offset + item_length])
                decoded = raw_value.split(b"\x00", 1)[0].decode("latin-1", errors="ignore").strip()
                if decoded:
                    values.append(decoded)
            offset += item_length
            offset = _align_4(offset)

        if name:
            elements[name] = {
                "vr": vr or None,
                "vm": vm,
                "values": values
            }

    if not elements:
        return None

    return {
        "format": fmt,
        "element_count": len(elements),
        "elements": elements
    }


def extract_csa_payload(ds: pydicom.Dataset, tag: Tuple[int, int]) -> Tuple[Optional[str], Optional[str]]:
    elem = ds.get(tag)
    if elem is None:
        return None, None
    value = elem.value
    if isinstance(value, str):
        raw = value.encode("latin-1", errors="ignore")
    elif isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
    else:
        return None, None
    digest = hashlib.sha256(raw).hexdigest()
    parsed = parse_csa_header(raw)
    if not parsed:
        return None, digest
    return json.dumps(parsed, ensure_ascii=True), digest


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
    meta.sop_instance_uid = safe_getattr(ds, 'SOPInstanceUID')

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

    # Siemens CSA headers (0029,1010) and (0029,1020)
    meta.csa_image_header_json, meta.csa_image_header_hash = extract_csa_payload(ds, (0x0029, 0x1010))
    meta.csa_series_header_json, meta.csa_series_header_hash = extract_csa_payload(ds, (0x0029, 0x1020))

    meta.private_tags = extract_private_tags(ds, meta)
    if meta.private_tags:
        fingerprint_items = [
            f"{tag.get('creator','')}|{tag.get('group_hex','')}|{tag.get('element_hex','')}|{tag.get('value_hash','')}"
            for tag in meta.private_tags
        ]
        fingerprint_items.sort()
        joined = "\n".join(fingerprint_items).encode("utf-8")
        meta.private_payload_fingerprint = hashlib.sha256(joined).hexdigest()

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

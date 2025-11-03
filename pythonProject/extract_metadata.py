#!/usr/bin/env python3
"""
Simple DICOM Metadata Extractor
Extracts all important medical and manufacturer metadata from DICOM files.
"""

import pydicom
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict, field
import json

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
    slice_thickness: Optional[float] = None
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
    number_of_slices: Optional[int] = None
    
    
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
    meta.slice_thickness = safe_getattr(ds, 'SliceThickness', float)
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
    
    # Private tags are no longer extracted (not human-readable, take up space, not useful)
    
    return meta


def extract_all_metadata(directory: Path) -> List[DICOMMetadata]:
    """Extract metadata from all DICOM files in a directory"""
    metadata_list = []
    dcm_files = list(directory.rglob("*.dcm"))
    
    for dcm_file in dcm_files:
        # Skip macOS metadata files
        if dcm_file.name.startswith('._') or '__MACOSX' in str(dcm_file):
            continue
        
        meta = extract_metadata(dcm_file)
        if meta:
            metadata_list.append(meta)
    
    return metadata_list


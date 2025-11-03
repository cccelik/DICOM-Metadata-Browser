#!/usr/bin/env python3
"""
Create a mock DICOM file for testing
"""

from pydicom import Dataset
from pydicom.uid import generate_uid
from datetime import datetime
import os

def create_mock_dicom(patient_name="Max Musterman", output_path="mock_dicom.dcm"):
    """Create a mock DICOM file with specified patient name"""
    
    # Create a basic DICOM dataset
    ds = Dataset()
    
    # Set file meta information (required for valid DICOM file)
    ds.file_meta = Dataset()
    ds.file_meta.TransferSyntaxUID = "1.2.840.10008.1.2.1"  # Explicit VR Little Endian
    ds.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"  # CT Image Storage
    ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    ds.file_meta.ImplementationClassUID = "1.2.3.4.5.6.7.8.9"
    ds.file_meta.ImplementationVersionName = "MOCK_DICOM_1.0"
    
    # Patient Information (required)
    ds.PatientName = patient_name
    ds.PatientID = "TEST123456"
    ds.PatientBirthDate = "19800101"
    ds.PatientSex = "M"
    ds.PatientAge = "044Y"
    ds.PatientWeight = 75.5  # kg
    ds.PatientSize = 1.80  # meters
    
    # Study Information (required)
    ds.StudyInstanceUID = generate_uid()
    ds.StudyDate = datetime.now().strftime("%Y%m%d")
    ds.StudyTime = datetime.now().strftime("%H%M%S")
    ds.StudyDescription = "Test Scan"
    ds.StudyID = "STUDY001"
    ds.AccessionNumber = "ACC001"
    
    # Series Information (required)
    ds.SeriesInstanceUID = generate_uid()
    ds.SeriesNumber = 1
    ds.SeriesDate = datetime.now().strftime("%Y%m%d")
    ds.SeriesTime = datetime.now().strftime("%H%M%S")
    ds.SeriesDescription = "Test Series"
    ds.Modality = "CT"
    
    # Image Information (required for image storage)
    ds.SOPInstanceUID = generate_uid()
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"  # CT Image Storage
    
    # Acquisition Information
    ds.AcquisitionDate = datetime.now().strftime("%Y%m%d")
    ds.AcquisitionTime = datetime.now().strftime("%H%M%S")
    
    # Manufacturer Information
    ds.Manufacturer = "Mock Manufacturer"
    ds.ManufacturerModelName = "Mock Scanner Model"
    ds.StationName = "MOCK_STATION_01"
    ds.SoftwareVersions = ["1.0.0"]
    ds.DeviceSerialNumber = "MOCK12345"
    ds.InstitutionName = "Mock Institution"
    
    # Image Geometry (minimal required for CT)
    ds.Rows = 512
    ds.Columns = 512
    ds.BitsAllocated = 16
    ds.BitsStored = 12
    ds.HighBit = 11
    ds.PixelSpacing = [0.5, 0.5]
    ds.SliceThickness = 1.0
    ds.SpacingBetweenSlices = 1.0
    
    # Create a simple dummy pixel array (small for file size)
    import numpy as np
    ds.PixelData = np.zeros((512, 512), dtype=np.uint16).tobytes()
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    
    # Save the file (with preamble and file meta)
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.save_as(output_path, write_like_original=False)
    
    print(f"✓ Created mock DICOM file: {output_path}")
    print(f"  Patient Name: {patient_name}")
    print(f"  Patient ID: {ds.PatientID}")
    print(f"  Study Date: {ds.StudyDate}")
    print(f"  Modality: {ds.Modality}")
    
    return ds


if __name__ == "__main__":
    import sys
    
    output_path = "mock_max_musterman.dcm"
    if len(sys.argv) > 1:
        output_path = sys.argv[1]
    
    ds = create_mock_dicom(patient_name="Max Musterman", output_path=output_path)
    print(f"\nFile saved to: {os.path.abspath(output_path)}")
    print(f"\nYou can test it with:")
    print(f"  python3 process_dicom.py {os.path.dirname(os.path.abspath(output_path))}")


# DICOM Metadata Extractor

Simple tool to extract and browse medical and manufacturer metadata from DICOM files.

## Features

- Extracts all important DICOM tags (patient, study, series, manufacturer, nuclear medicine)
- Stores metadata in SQLite database
- Clean web UI to browse studies and series
- Supports all DICOM modalities (PET, CT, MR, NM, etc.)

## Installation

```bash
pip install -r requirements.txt
```

## Usage

### 1. Process DICOM Files

Process a directory containing DICOM files:

```bash
python3 process_dicom.py <dicom_directory> [database_name]
```

**Examples:**

Process a single scan directory:
```bash
python3 process_dicom.py /path/to/scan_directory dicom_metadata.db
```

Process multiple scans at once (works with any directory structure):
```bash
python3 process_dicom.py /path/to/parent_directory dicom_metadata.db
```

**How it works:**

The script automatically detects the directory structure:
- If the directory contains subdirectories with DICOM files, it processes each subdirectory as a separate scan
- Otherwise, it processes all DICOM files recursively from the given directory
- All scans are stored in the same database so you can browse them together in the web UI
- Works with any directory names (no hardcoded assumptions)

**Deduplication:**

The script prevents duplicate series while allowing incremental updates:
- Checks if individual series (by SeriesInstanceUID) already exist before inserting
- **New series can be added to existing studies** - if you add files to a study, only new series are added
- Existing series are automatically skipped - no duplicates
- Database is never rewritten - only new data is appended
- Running the script multiple times is safe - duplicates are automatically detected and skipped

### 2. Start Web UI

```bash
python3 webui.py
```

Then open your browser to: http://127.0.0.1:5001

## Project Structure

- `extract_metadata.py` - Extracts all important DICOM tags
- `store_metadata.py` - SQLite database storage
- `process_dicom.py` - Command-line processor
- `webui.py` - Web interface for browsing metadata
- `templates/` - HTML templates for web UI

## What Gets Extracted

- **Patient Info**: ID, name, birth date, sex, age, weight
- **Study Info**: UID, date, time, description, accession number
- **Series Info**: UID, number, description, modality
- **Manufacturer Info**: Manufacturer, model, software version, station name
- **Acquisition Info**: Date, time, slice thickness, KVP, exposure
- **Nuclear Medicine**: Radiopharmaceutical, injected activity, injection time
- **Private Tags**: Manufacturer-specific private tags

## Database Schema

All metadata is stored in a single `dicom_metadata` table with comprehensive columns for all DICOM tags.


# DICOM Metadata Browser

[![Tests](https://github.com/cccelik/BAProject/actions/workflows/tests.yml/badge.svg)](https://github.com/cccelik/BAProject/actions/workflows/tests.yml)

Extract DICOM metadata into SQLite, explore it in a Flask web UI, and run QA-focused analyses (timing, dose, metadata completeness, and private-tag provenance).

## What This Project Does

- Ingests DICOM files/folders/archives into SQLite (`dicom_metadata` + `private_tag` tables).
- Detects DICOM candidates robustly (`.dcm`, `.ima`, Part 10 signature, extensionless parse fallback).
- Computes representative-series flags per study to avoid QA double-counting.
- Exposes a web UI for filtering, dashboard analytics, study inspection, and CSV export.
- Supports anonymized database export with path scrubbing and private-tag payload scrubbing.
- Supports CSV export with selectable fields, optional anonymization, and an explicit export-language selector.

## Requirements

- Python 3.10+ (tested with 3.12 in CI)
- `pip`

Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Quick Start

### 1) Process DICOM data into a databank

```bash
python3 process_dicom.py /path/to/dicom_dir dicom_metadata.db
```

### 2) Start the web UI

```bash
python3 webui.py
```

Open `http://127.0.0.1:5001`.

## CLI Usage

### Main processor

```text
python3 process_dicom.py <input_path> [db_name_or_path]
  --no-subdirs           Treat input as one scan (no scan-folder discovery)
  --max-workers N        Set worker processes
  --timing               Print stage/total timings
  --skip-existing-paths  Skip rows whose relative file path already exists
  --no-auto-workers      Disable worker auto-tuning
  --verbose              Print detailed progress
```

Examples:

```bash
# Standard folder ingest
python3 process_dicom.py /path/to/dicom_dir my_project

# Parent folder containing scan subdirectories
python3 process_dicom.py /path/to/parent_dir dicom_metadata.db

# Single-scan mode
python3 process_dicom.py /path/to/dicom_dir dicom_metadata.db --no-subdirs

# Archive ingest
python3 process_dicom.py /path/to/archive.zip dicom_metadata.db
python3 process_dicom.py /path/to/archive.7z dicom_metadata.db

# Single file (including extensionless vendor files)
python3 process_dicom.py /path/to/file dicom_metadata.db
```

### Metadata-only extraction (JSON)

```bash
python3 -m dicom_browser.extract_metadata /path/to/dicom_dir
python3 -m dicom_browser.extract_metadata /path/to/dicom_dir -o /tmp/metadata.json -m 8 -t
```

### One-per-series helper

```bash
python3 extract_one_per_series.py /path/to/input_root /path/to/output_root
```

## Web UI

### Start and port

```bash
python3 webui.py
PORT=5050 python3 webui.py
```

### Select databank

Use query parameter (filename only):

```text
http://127.0.0.1:5001/?db=another.db
```

### Anonymized databank export

From databank menu: **Export Anonymized DB**.

Behavior highlights:

- Default anonymization fields are always applied.
- `file_path` anonymization is on by default.
- Related path sources are scrubbed (`scan_root`, `private_tag.file_path`).
- High-risk text fields are blanked where configured.
- Private-tag payload columns are scrubbed.
- Export runs with `secure_delete` + `VACUUM` to reduce recoverable deleted text.

### CSV export

From the study page or databank page: **Export CSV**.

Behavior highlights:

- Field selection is configurable in the export modal.
- CSV anonymization can be enabled without modifying the databank.
- Export language can be selected directly in the modal (`English` or `Deutsch`).
- CSV headers follow the selected export language, independent of the current page language.

## Testing

Run all tests locally:

```bash
python3 -m unittest discover -s tests -v
```

Current automated CI:

- GitHub Actions workflow: `.github/workflows/tests.yml`
- Triggered on push to `main`/`master` and pull requests
- Sets up Python 3.12, installs `requirements.txt`, runs full unit suite

## Linting

```bash
pip install ruff flake8
ruff check .
flake8 .
ruff check . --fix
```

Config:

- `pyproject.toml` (Ruff)
- `.flake8` (Flake8)

## Repository Structure

- `webui.py`: Flask app and UI routes
- `process_dicom.py`: ingest pipeline and representative-series pruning
- `extract_one_per_series.py`: one-file-per-series helper
- `dicom_browser/`: shared application package
- `dicom_browser/extract_metadata.py`: DICOM parser and private-tag extraction
- `dicom_browser/store_metadata.py`: SQLite schema and write path
- `dicom_browser/dicom_discovery.py`: shared DICOM candidate detection
- `dicom_browser/qa_utils.py`: shared QA and representative-series helpers
- `dicom_browser/export_utils.py`: CSV export formatting and anonymization helpers
- `dicom_browser/study_service.py`: study-detail payload assembly
- `dicom_browser/dashboard_service.py`: dashboard aggregation logic
- `dicom_browser/translations.py`: translation dictionaries
- `scripts/`: auxiliary scripts such as mock DICOM generation
- `templates/`: HTML templates
- `tests/`: unit/integration tests
- `Databanks/`: SQLite databanks
- `Efficient Data Access and Storage Optimization for PET:CT Imaging Data/`: thesis source files

## Notes

- CLI accepts absolute DB paths; non-absolute names are normalized into `Databanks/<name>.db`.
- UI `db` parameter is treated as a filename and resolved inside `Databanks/`.
- Duplicate series ingestion is prevented by unique `series_instance_uid`.
- The root directory is intentionally kept small; most reusable Python code now lives in `dicom_browser/`.

## Thesis Build

```bash
cd Efficient\ Data\ Access\ and\ Storage\ Optimization\ for\ PET:CT\ Imaging\ Data
latexmk -pdf -interaction=nonstopmode -file-line-error main.tex
```

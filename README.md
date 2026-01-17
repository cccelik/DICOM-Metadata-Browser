# DICOM Metadata Extractor

Tooling to extract DICOM metadata into SQLite and browse it via a lightweight web UI.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run options (all supported ways)

### 1) Process DICOMs into SQLite (CLI)

Process a directory of DICOM files (recurses). Database files are stored in `Databanks/` by default:

```bash
python3 process_dicom.py /path/to/dicom_dir dicom_metadata.db
```

Process a parent directory containing multiple scan subdirectories:

```bash
python3 process_dicom.py /path/to/parent_dir dicom_metadata.db
```

Use just a name (extension optional):

```bash
python3 process_dicom.py /path/to/dicom_dir my_project
```

Treat the input as a single scan (no subdirectory discovery):

```bash
python3 process_dicom.py /path/to/dicom_dir dicom_metadata.db --no-subdirs
```

Process a ZIP/7Z archive directly (auto-extracted to a temp folder):

```bash
python3 process_dicom.py /path/to/archive.zip dicom_metadata.db
python3 process_dicom.py /path/to/archive.7z dicom_metadata.db
```

Optional flags:

```bash
python3 process_dicom.py /path/to/dicom_dir dicom_metadata.db --max-workers 8 --timing
```

All CLI parameters:

```text
python3 process_dicom.py <dicom_dir> [db_name_or_path]
  --no-subdirs           Treat the entire input as a single scan.
  --max-workers N        Maximum worker processes (default: auto based on file count).
  --timing               Print elapsed time.
  --skip-existing-paths  Skip files whose relative paths already exist in the database.
  --no-auto-workers      Disable auto-tuning worker count.
  --verbose              Print detailed processing output.
```

### 2) Browse metadata in the Web UI

Start the server (defaults to port 5001):

```bash
python3 webui.py
```

Open: `http://127.0.0.1:5001`

Use a custom port:

```bash
PORT=5050 python3 webui.py
```

Select a different database in the UI by URL parameter (name or file, loaded from `Databanks/`):

```
http://127.0.0.1:5001/?db=another.db
```

### 3) Extract metadata as JSON (no database)

Dump metadata to stdout:

```bash
python3 extract_metadata.py /path/to/dicom_dir
```

Write JSON to a file:

```bash
python3 extract_metadata.py /path/to/dicom_dir -o /tmp/metadata.json
```

Include timing and control parallelism:

```bash
python3 extract_metadata.py /path/to/dicom_dir -m 8 -t
```

### 4) Inspect DICOM tags for a single file

```bash
python3 identify_tags.py /path/to/file.dcm
```

### 5) Generate a mock DICOM for quick testing

```bash
python3 create_mock_dicom.py
```

Write the mock file to a custom location:

```bash
python3 create_mock_dicom.py /tmp/mock_patient.dcm
```

## Notes

- The main database table is `dicom_metadata`.
- The CLI prevents duplicate series by `SeriesInstanceUID`, so re-processing is safe.
- Sample data may be available in `MIRROR_A/` or `MIRROR_A.7z`.

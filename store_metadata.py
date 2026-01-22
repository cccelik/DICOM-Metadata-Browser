#!/usr/bin/env python3
"""
Simple SQLite storage for DICOM metadata
"""

import sqlite3
from pathlib import Path
from typing import List, Optional
from extract_metadata import DICOMMetadata

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS dicom_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT,
    
    -- Patient Information
    patient_id TEXT,
    patient_name TEXT,
    patient_birth_date TEXT,
    patient_sex TEXT,
    patient_age TEXT,
    patient_weight REAL,
    patient_size REAL,
    
    -- Study Information
    study_instance_uid TEXT,
    study_date TEXT,
    study_time TEXT,
    study_description TEXT,
    study_id TEXT,
    accession_number TEXT,
    referring_physician_name TEXT,
    
    -- Series Information
    series_instance_uid TEXT UNIQUE,
    sop_instance_uid TEXT,
    series_number INTEGER,
    series_date TEXT,
    series_time TEXT,
    series_description TEXT,
    protocol_name TEXT,
    modality TEXT,
    body_part_examined TEXT,
    
    -- Manufacturer Information
    manufacturer TEXT,
    manufacturer_model_name TEXT,
    station_name TEXT,
    software_version TEXT,
    device_serial_number TEXT,
    institution_name TEXT,
    institution_address TEXT,
    
    -- Acquisition Information
    acquisition_date TEXT,
    acquisition_time TEXT,
    patient_position TEXT,
    scanning_sequence TEXT,
    sequence_variant TEXT,
    scan_options TEXT,
    acquisition_type TEXT,
    slice_thickness REAL,
    reconstruction_diameter REAL,
    reconstruction_algorithm TEXT,
    convolution_kernel TEXT,
    filter_type TEXT,
    spiral_pitch_factor REAL,
    ctdivol REAL,
    dlp REAL,
    kvp REAL,
    exposure_time REAL,
    exposure REAL,
    tube_current REAL,
    
    -- Nuclear Medicine Specific
    radiopharmaceutical TEXT,
    injected_activity REAL,
    injected_activity_unit TEXT,
    injection_time TEXT,
    injection_date TEXT,
    half_life REAL,
    decay_correction TEXT,
    
    -- Additional Radiopharmaceutical Information
    radiopharmaceutical_volume REAL,  -- (0018,1071)
    radionuclide_total_dose REAL,  -- (0018,1074)
    
    -- Image Information
    image_type TEXT,
    pixel_spacing TEXT,
    image_orientation_patient TEXT,
    slice_location REAL,
    number_of_frames INTEGER,
    frame_time REAL,
    number_of_slices INTEGER,

    -- Private (CTP anonymizer) metadata
    ctp_collection TEXT,
    ctp_subject_id TEXT,
    ctp_private_flag_raw TEXT,
    ctp_private_flag_int INTEGER,

    -- Siemens CSA headers (decoded JSON)
    csa_image_header_json TEXT,
    csa_series_header_json TEXT,
    csa_image_header_hash TEXT,
    csa_series_header_hash TEXT,
    private_payload_fingerprint TEXT,
    
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Primary indexes for unique lookups
CREATE INDEX IF NOT EXISTS idx_patient_id ON dicom_metadata(patient_id);
CREATE INDEX IF NOT EXISTS idx_study_uid ON dicom_metadata(study_instance_uid);
CREATE INDEX IF NOT EXISTS idx_series_uid ON dicom_metadata(series_instance_uid);
CREATE INDEX IF NOT EXISTS idx_sop_uid ON dicom_metadata(sop_instance_uid);
CREATE INDEX IF NOT EXISTS idx_modality ON dicom_metadata(modality);
CREATE INDEX IF NOT EXISTS idx_manufacturer ON dicom_metadata(manufacturer);

-- Search indexes (for LIKE queries and filtering)
CREATE INDEX IF NOT EXISTS idx_patient_name ON dicom_metadata(patient_name);
CREATE INDEX IF NOT EXISTS idx_radiopharmaceutical ON dicom_metadata(radiopharmaceutical);
CREATE INDEX IF NOT EXISTS idx_study_date ON dicom_metadata(study_date);
CREATE INDEX IF NOT EXISTS idx_study_id ON dicom_metadata(study_id);
CREATE INDEX IF NOT EXISTS idx_accession_number ON dicom_metadata(accession_number);

-- Composite indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_patient_study ON dicom_metadata(patient_id, study_instance_uid);
CREATE INDEX IF NOT EXISTS idx_study_date_modality ON dicom_metadata(study_date DESC, modality);
CREATE INDEX IF NOT EXISTS idx_manufacturer_modality ON dicom_metadata(manufacturer, modality);

-- Full-text search index for text fields (if FTS5 available)
-- CREATE VIRTUAL TABLE IF NOT EXISTS dicom_fts USING fts5(
--     patient_name, patient_id, study_description, 
--     radiopharmaceutical, manufacturer, modality
-- );

CREATE TABLE IF NOT EXISTS private_tag (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sop_instance_uid TEXT,
    series_instance_uid TEXT,
    study_instance_uid TEXT,
    file_path TEXT,
    manufacturer TEXT,
    modality TEXT,
    group_hex TEXT,
    element_hex TEXT,
    creator TEXT,
    vr TEXT,
    value_text TEXT,
    value_num REAL,
    value_json TEXT,
    value_hex TEXT,
    byte_len INTEGER,
    value_hash TEXT,
    classification TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(series_instance_uid, group_hex, element_hex, creator, value_hash)
);

CREATE INDEX IF NOT EXISTS idx_private_series ON private_tag(series_instance_uid);
CREATE INDEX IF NOT EXISTS idx_private_creator ON private_tag(creator);
CREATE INDEX IF NOT EXISTS idx_private_classification ON private_tag(classification);
"""


def init_database(db_path: str, optimize: bool = True):
    """Initialize database with schema and performance optimizations
    
    Args:
        db_path: Path to SQLite database file
        optimize: If True, apply performance optimizations for large datasets
    """
    conn = sqlite3.connect(db_path)
    
    # Performance optimizations for large datasets
    if optimize:
        # Enable Write-Ahead Logging (WAL) mode for better concurrency and performance
        conn.execute("PRAGMA journal_mode=WAL")
        # Increase cache size (default 2MB, set to 64MB for large datasets)
        conn.execute("PRAGMA cache_size=-64000")  # Negative = KB, so 64MB
        # Increase page size if database is new (better for large datasets)
        conn.execute("PRAGMA page_size=4096")
        # Optimize synchronous writes (NORMAL for WAL is safe and faster than FULL)
        conn.execute("PRAGMA synchronous=NORMAL")
        # Increase temp store for large sorts/joins
        conn.execute("PRAGMA temp_store=MEMORY")
        # Enable mmap for faster reads
        conn.execute("PRAGMA mmap_size=268435456")  # 256MB
        # Optimize query planner
        conn.execute("PRAGMA optimize")
    
    conn.executescript(DB_SCHEMA)

    # Ensure new columns exist in older databases
    cursor = conn.execute("PRAGMA table_info(dicom_metadata)")
    existing_cols = {row[1] for row in cursor.fetchall()}
    migrations = [
        ("ctp_collection", "TEXT"),
        ("ctp_subject_id", "TEXT"),
        ("ctp_private_flag_raw", "TEXT"),
        ("ctp_private_flag_int", "INTEGER"),
        ("csa_image_header_json", "TEXT"),
        ("csa_series_header_json", "TEXT"),
        ("csa_image_header_hash", "TEXT"),
        ("csa_series_header_hash", "TEXT"),
        ("private_payload_fingerprint", "TEXT"),
        ("sop_instance_uid", "TEXT"),
        ("protocol_name", "TEXT"),
        ("patient_position", "TEXT"),
        ("scanning_sequence", "TEXT"),
        ("sequence_variant", "TEXT"),
        ("scan_options", "TEXT"),
        ("acquisition_type", "TEXT"),
        ("reconstruction_diameter", "REAL"),
        ("reconstruction_algorithm", "TEXT"),
        ("convolution_kernel", "TEXT"),
        ("filter_type", "TEXT"),
        ("spiral_pitch_factor", "REAL"),
        ("ctdivol", "REAL"),
        ("dlp", "REAL"),
        ("number_of_frames", "INTEGER"),
        ("frame_time", "REAL"),
    ]
    for col_name, col_type in migrations:
        if col_name not in existing_cols:
            conn.execute(f"ALTER TABLE dicom_metadata ADD COLUMN {col_name} {col_type}")
    conn.commit()
    return conn


def study_exists(conn: sqlite3.Connection, study_uid: str) -> bool:
    """Check if a study already exists in the database"""
    if not study_uid:
        return False
    cursor = conn.execute(
        "SELECT COUNT(*) FROM dicom_metadata WHERE study_instance_uid = ?",
        (study_uid,)
    )
    count = cursor.fetchone()[0]
    return count > 0


def series_exists(conn: sqlite3.Connection, series_uid: str) -> bool:
    """Check if a series already exists in the database"""
    if not series_uid:
        return False
    cursor = conn.execute(
        "SELECT COUNT(*) FROM dicom_metadata WHERE series_instance_uid = ?",
        (series_uid,)
    )
    count = cursor.fetchone()[0]
    return count > 0


def insert_metadata(conn: sqlite3.Connection, metadata: DICOMMetadata, file_path: str, skip_existing: bool = True, commit: bool = True):
    """Insert metadata into database
    
    Args:
        conn: Database connection
        metadata: DICOM metadata to insert
        file_path: Path to the DICOM file
        skip_existing: If True, skip if series already exists (prevents duplicates)
    
    Returns:
        tuple: (inserted: bool, reason: str)
    """
    data = metadata.to_dict()
    private_tags = data.pop("private_tags", [])
    data['file_path'] = file_path
    
    columns = ', '.join(data.keys())
    placeholders = ', '.join(['?' for _ in data])
    values = list(data.values())
    
    query = f"""
    INSERT OR IGNORE INTO dicom_metadata ({columns})
    VALUES ({placeholders})
    """
    
    try:
        cursor = conn.execute(query, values)
        if commit:
            conn.commit()
        # Check if row was actually inserted
        if cursor.rowcount > 0:
            if private_tags:
                insert_private_tags(conn, metadata, file_path, private_tags, commit=commit)
            return True, "inserted"
        if skip_existing and metadata.series_instance_uid:
            return False, "series_exists"
        return False, "already_exists"
    except sqlite3.IntegrityError:
        # Series UID already exists (unique constraint)
        if commit:
            conn.commit()
        return False, "integrity_error"


def store_metadata_batch(db_path: str, metadata_list: List[DICOMMetadata], file_paths: List[str], batch_size: int = 1000):
    """Store a batch of metadata records with optimized batch insertion
    
    Args:
        db_path: Path to database
        metadata_list: List of metadata objects
        file_paths: List of file paths
        batch_size: Number of records to insert per transaction (default 1000)
    """
    if not metadata_list:
        return
    
    conn = init_database(db_path, optimize=True)
    
    # Prepare all data first
    all_data = []
    for metadata, file_path in zip(metadata_list, file_paths):
        data = metadata.to_dict()
        data.pop("private_tags", None)
        data['file_path'] = file_path
        
        all_data.append(data)
    
    # Get column names from first item
    columns = ', '.join(all_data[0].keys())
    placeholders = ', '.join(['?' for _ in all_data[0].keys()])
    
    # Batch insert with executemany
    query = f"INSERT OR IGNORE INTO dicom_metadata ({columns}) VALUES ({placeholders})"
    
    # Process in batches for better performance and memory management
    for i in range(0, len(all_data), batch_size):
        batch = all_data[i:i + batch_size]
        values_list = [list(item.values()) for item in batch]
        conn.executemany(query, values_list)
        # Insert private tags after base metadata to avoid FK/order issues.
        for metadata, file_path in zip(metadata_list[i:i + batch_size], file_paths[i:i + batch_size]):
            if metadata.private_tags:
                insert_private_tags(conn, metadata, file_path, metadata.private_tags, commit=False)
        conn.commit()
    
    conn.close()


def insert_private_tags(
    conn: sqlite3.Connection,
    metadata: DICOMMetadata,
    file_path: str,
    private_tags: List[dict],
    commit: bool = True
):
    if not private_tags:
        return
    values = []
    for tag in private_tags:
        values.append((
            tag.get("sop_instance_uid"),
            metadata.series_instance_uid,
            metadata.study_instance_uid,
            file_path,
            metadata.manufacturer,
            metadata.modality,
            tag.get("group_hex"),
            tag.get("element_hex"),
            tag.get("creator"),
            tag.get("vr"),
            tag.get("value_text"),
            tag.get("value_num"),
            tag.get("value_json"),
            tag.get("value_hex"),
            tag.get("byte_len"),
            tag.get("value_hash"),
            tag.get("classification"),
        ))
    conn.executemany(
        """
        INSERT OR IGNORE INTO private_tag (
            sop_instance_uid,
            series_instance_uid,
            study_instance_uid,
            file_path,
            manufacturer,
            modality,
            group_hex,
            element_hex,
            creator,
            vr,
            value_text,
            value_num,
            value_json,
            value_hex,
            byte_len,
            value_hash,
            classification
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        values
    )
    if commit:
        conn.commit()


def get_all_metadata(db_path: str) -> List[dict]:
    """Retrieve all metadata from database"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("SELECT * FROM dicom_metadata ORDER BY study_date DESC, series_number ASC")
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return results


def get_metadata_by_study(db_path: str, study_uid: str) -> List[dict]:
    """Get all series for a specific study"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        "SELECT * FROM dicom_metadata WHERE study_instance_uid = ? ORDER BY series_number ASC",
        (study_uid,)
    )
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return results


def get_studies_summary(db_path: str) -> List[dict]:
    """Get summary of all studies"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("""
        SELECT 
            study_instance_uid,
            patient_id,
            patient_name,
            study_date,
            study_time,
            study_description,
            modality,
            manufacturer,
            COUNT(*) as series_count
        FROM dicom_metadata
        GROUP BY study_instance_uid
        ORDER BY study_date DESC
    """)
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return results

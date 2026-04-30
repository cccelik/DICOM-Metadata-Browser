#!/usr/bin/env python3
"""
Clean Web UI for DICOM Metadata Browser
"""

import csv
import io
import math
import os
import re
import secrets
import shutil
import sqlite3
import statistics
import string
import tempfile
import zipfile
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from flask import (
    Flask,
    Response,
    after_this_request,
    jsonify,
    render_template,
    request,
    send_file,
    send_from_directory,
    session,
)

from dicom_browser.dashboard_service import build_dashboard_payload as build_dashboard_payload_service
from dicom_browser.export_utils import (
    _generate_anonymized_value as generate_anonymized_value_impl,
    anonymize_export_value as anonymize_export_value_impl,
    build_anonymize_fields as build_anonymize_fields_impl,
    build_export_sections as build_export_sections_impl,
    calculate_injection_delay as calculate_injection_delay_impl,
    format_date as format_date_impl,
    format_delay as format_delay_impl,
    format_export_value as format_export_value_impl,
    format_patient_name as format_patient_name_impl,
    format_private_timestamp as format_private_timestamp_impl,
    format_time as format_time_impl,
    is_radiopharm_modality as is_radiopharm_modality_impl,
    parse_pet_dose_report as parse_pet_dose_report_impl,
    resolve_csv_anonymize_fields as resolve_csv_anonymize_fields_impl,
    resolve_export_fields as resolve_export_fields_impl,
    resolve_export_query_fields as resolve_export_query_fields_impl,
    sanitize_filename as sanitize_filename_impl,
    write_csv_export_rows as write_csv_export_rows_impl,
)
from process_dicom import process_directory
from dicom_browser.qa_utils import (
    compute_delay_minutes as shared_compute_delay_minutes,
    compute_dose_from_row as shared_compute_dose_from_row,
    compute_dose_per_kg as shared_compute_dose_per_kg,
    get_patient_weight as shared_get_patient_weight,
    parse_db_float as shared_parse_db_float,
    parse_time_to_24hour as shared_parse_time_to_24hour,
    select_study_representatives as shared_select_study_representatives,
)
from dicom_browser.store_metadata import init_database
from dicom_browser.study_service import build_study_detail_payload as build_study_detail_payload_service
from dicom_browser.translations import get_translation

app = Flask(__name__)
app.secret_key = os.urandom(24)  # Required for sessions

BASE_DIR = Path(__file__).resolve().parent
DATABANK_DIR = BASE_DIR / "Databanks"
DEFAULT_DB_NAME = "dicom_metadata.db"
DEFAULT_DB = str(DATABANK_DIR / DEFAULT_DB_NAME)

EXPORT_SECTIONS = [
    {
        "key": "patient",
        "label_key": "patient_information",
        "fields": [
            {"name": "patient_name", "label_key": "patient_name", "default": True},
            {"name": "patient_id", "label_key": "patient_id", "default": True},
            {"name": "patient_birth_date", "label_key": "patient_birth_date", "default": True},
            {"name": "patient_sex", "label_key": "patient_sex", "default": True},
            {"name": "patient_age", "label_key": "patient_age", "default": True},
            {"name": "patient_weight", "label_key": "patient_weight", "default": True},
            {"name": "patient_size", "label_key": "patient_height", "default": True},
            {"name": "bmi", "label_key": "bmi"},
        ],
    },
    {
        "key": "study",
        "label_key": "study_information",
        "fields": [
            {"name": "study_instance_uid", "label_key": "study_uid"},
            {"name": "study_date", "label_key": "study_date", "default": True},
            {"name": "study_time", "label_key": "study_time", "default": True},
            {"name": "study_description", "label_key": "study_description", "default": True},
            {"name": "study_id", "label_key": "study_id"},
            {"name": "accession_number", "label_key": "accession_number"},
            {"name": "referring_physician_name", "label_key": "referring_physician"},
        ],
    },
    {
        "key": "series",
        "label_key": "series_information",
        "fields": [
            {"name": "series_instance_uid", "label_key": "series_uid"},
            {"name": "series_number", "label_key": "series_number", "default": True},
            {"name": "series_date", "label_key": "series_date"},
            {"name": "series_time", "label_key": "series_time"},
            {"name": "series_description", "label_key": "description", "default": True},
            {"name": "protocol_name", "label_key": "protocol_name", "default": True},
            {"name": "modality", "label_key": "modality", "default": True},
            {"name": "body_part_examined", "label_key": "body_part", "default": True},
            {"name": "series_type", "label_key": "series_type", "default": True},
        ],
    },
    {
        "key": "manufacturer",
        "label_key": "manufacturer_information",
        "fields": [
            {"name": "manufacturer", "label_key": "manufacturer", "default": True},
            {"name": "manufacturer_model_name", "label_key": "model", "default": True},
            {"name": "station_name", "label_key": "station_name"},
            {"name": "software_version", "label_key": "software_version"},
            {"name": "device_serial_number", "label_key": "device_serial_number"},
            {"name": "institution_name", "label_key": "institution"},
            {"name": "institution_address", "label_key": "institution_address"},
        ],
    },
    {
        "key": "acquisition",
        "label_key": "acquisition_information",
        "fields": [
            {"name": "acquisition_date", "label_key": "acquisition_date", "default": True},
            {"name": "acquisition_time", "label_key": "acquisition_time", "default": True},
            {"name": "patient_position", "label_key": "patient_position"},
            {"name": "scanning_sequence", "label_key": "scanning_sequence", "default": True},
            {"name": "sequence_variant", "label_key": "sequence_variant", "default": True},
            {"name": "scan_options", "label_key": "scan_options", "default": True},
            {"name": "acquisition_type", "label_key": "acquisition_type"},
            {"name": "slice_thickness", "label_key": "slice_thickness"},
            {"name": "reconstruction_diameter", "label_key": "reconstruction_diameter"},
            {"name": "reconstruction_algorithm", "label_key": "reconstruction_algorithm"},
            {"name": "convolution_kernel", "label_key": "convolution_kernel", "default": True},
            {"name": "reconstruction_method", "label_key": "reconstruction_method", "default": True},
            {"name": "filter_type", "label_key": "filter_type"},
            {"name": "spiral_pitch_factor", "label_key": "spiral_pitch_factor"},
            {"name": "ctdivol", "label_key": "ctdivol"},
            {"name": "dlp", "label_key": "dlp"},
            {"name": "kvp", "label_key": "kvp"},
            {"name": "exposure_time", "label_key": "exposure_time"},
            {"name": "exposure", "label_key": "exposure"},
            {"name": "tube_current", "label_key": "tube_current"},
            {"name": "attenuation_correction_method", "label_key": "attenuation_correction_method"},
            {"name": "scatter_correction_method", "label_key": "scatter_correction_method"},
            {"name": "scatter_fraction_factor", "label_key": "scatter_fraction_factor"},
        ],
    },
    {
        "key": "nuclear",
        "label_key": "nuclear_medicine_information",
        "fields": [
            {"name": "radiopharmaceutical", "label_key": "radiopharmaceutical", "default": True},
            {"name": "injected_activity", "label_key": "injected_activity", "default": True},
            {"name": "injection_time", "label_key": "injection_time", "default": True},
            {"name": "injection_date", "label_key": "injection_date", "default": True},
            {"name": "half_life", "label_key": "half_life", "default": True},
            {"name": "decay_correction", "label_key": "decay_correction", "default": True},
            {"name": "radiopharmaceutical_volume", "label_key": "radiopharmaceutical_volume", "default": True},
            {"name": "radionuclide_total_dose", "label_key": "radionuclide_total_dose", "default": True},
            {"name": "uptake_delay", "label_key": "uptake_delay"},
            {"name": "dose_per_kg", "label_key": "dose_per_kg"},
        ],
    },
    {
        "key": "image",
        "label_key": "image_information",
        "fields": [
            {"name": "image_type", "label_key": "image_type"},
            {"name": "pixel_spacing", "label_key": "pixel_spacing", "default": True},
            {"name": "image_orientation_patient", "label_key": "image_orientation_patient"},
            {"name": "slice_location", "label_key": "slice_location"},
            {"name": "rows", "label_key": "rows", "default": True},
            {"name": "columns", "label_key": "columns"},
            {"name": "number_of_frames", "label_key": "number_of_frames", "default": True},
            {"name": "frame_time", "label_key": "frame_time"},
            {"name": "number_of_slices", "label_key": "number_of_slices", "default": True},
        ],
    },
    {
        "key": "ctp",
        "label_key": "ctp_private_metadata",
        "fields": [
            {"name": "ctp_collection", "label_key": "ctp_collection"},
            {"name": "ctp_subject_id", "label_key": "ctp_subject_id"},
            {"name": "ctp_private_flag_raw", "label_key": "ctp_private_flag_raw"},
            {"name": "ctp_private_flag_int", "label_key": "ctp_private_flag_int"},
        ],
    },
    {
        "key": "file",
        "label_key": "export_file_metadata",
        "fields": [
            {"name": "id", "label_key": "export_row_id"},
            {"name": "file_path", "label_key": "file_path"},
            {"name": "created_at", "label_key": "export_created_at"},
        ],
    },
]

EXPORT_FIELD_ORDER = [field["name"] for section in EXPORT_SECTIONS for field in section["fields"]]
EXPORT_DEFAULT_FIELDS = [
    field["name"]
    for section in EXPORT_SECTIONS
    for field in section["fields"]
    if field.get("default")
]
EXPORT_GROUP_CLEAR_FIELDS = [
    field["name"]
    for section in EXPORT_SECTIONS
    if section["key"] in {"patient", "study"}
    for field in section["fields"]
]

EXPORT_DERIVED_FIELDS = {
    "uptake_delay",
    "dose_per_kg",
    "bmi",
}

EXPORT_DERIVED_DEPENDENCIES = {
    "injection_date",
    "injection_time",
    "acquisition_date",
    "acquisition_time",
    "study_date",
    "study_time",
    "series_date",
    "series_time",
    "injected_activity",
}

EXPORT_DATE_FIELDS = {
    "patient_birth_date",
    "study_date",
    "series_date",
    "acquisition_date",
    "injection_date",
}

EXPORT_TIME_FIELDS = {
    "study_time",
    "series_time",
    "acquisition_time",
    "injection_time",
}

EXPORT_NUMERIC_FORMATS = {
    "patient_weight": ("kg", 2),
    "patient_size": ("m", 2),
    "slice_thickness": ("mm", 2),
    "reconstruction_diameter": ("mm", 2),
    "spiral_pitch_factor": (None, 3),
    "ctdivol": ("mGy", 2),
    "dlp": ("mGy*cm", 2),
    "kvp": ("kVp", 1),
    "exposure_time": ("ms", 2),
    "tube_current": ("mA", 2),
    "frame_time": ("ms", 2),
    "radiopharmaceutical_volume": ("ml", 2),
    "radionuclide_total_dose": ("MBq", 2),
    "half_life": ("s", 2),
}

ANONYMIZE_FIELDS = [
    {"name": "patient_name", "label_key": "patient_name", "default": True},
    {"name": "patient_id", "label_key": "patient_id", "default": True},
    {"name": "patient_birth_date", "label_key": "patient_birth_date"},
    {"name": "study_description", "label_key": "study_description", "default": True},
    {"name": "series_description", "label_key": "description", "default": True},
    {"name": "protocol_name", "label_key": "protocol_name", "default": True},
    {"name": "study_id", "label_key": "study_id"},
    {"name": "accession_number", "label_key": "accession_number"},
    {"name": "referring_physician_name", "label_key": "referring_physician"},
    {"name": "institution_name", "label_key": "institution"},
    {"name": "institution_address", "label_key": "institution_address"},
    {"name": "ctp_subject_id", "label_key": "ctp_subject_id"},
    {"name": "ctp_collection", "label_key": "ctp_collection"},
    {"name": "csa_image_header_json", "label_key": "csa_image_header_json", "default": True},
    {"name": "csa_series_header_json", "label_key": "csa_series_header_json", "default": True},
    {"name": "file_path", "label_key": "file_path", "default": True},
]

ANONYMIZE_FIELD_ORDER = [field["name"] for field in ANONYMIZE_FIELDS]
ANONYMIZE_DEFAULT_FIELDS = [field["name"] for field in ANONYMIZE_FIELDS if field.get("default")]

ANONYMIZE_BLANK_FIELDS = {
    "study_description",
    "series_description",
    "protocol_name",
    "csa_image_header_json",
    "csa_series_header_json",
}

def ensure_databank_dir() -> None:
    DATABANK_DIR.mkdir(parents=True, exist_ok=True)


def normalize_db_name(db_value: Optional[str]) -> str:
    if not db_value:
        return DEFAULT_DB_NAME
    name = Path(db_value).name.strip()
    if not name:
        return DEFAULT_DB_NAME
    if not name.lower().endswith(".db"):
        name = f"{name}.db"
    return name


def resolve_db_path(db_value: Optional[str]) -> str:
    ensure_databank_dir()
    name = normalize_db_name(db_value)
    return str(DATABANK_DIR / name)


def list_databanks() -> List[str]:
    ensure_databank_dir()
    return sorted(path.name for path in DATABANK_DIR.glob("*.db"))


def build_export_sections(translations: dict) -> tuple[List[dict], dict]:
    return build_export_sections_impl(translations, EXPORT_SECTIONS)


def build_anonymize_fields(translations: dict) -> List[dict]:
    return build_anonymize_fields_impl(translations, ANONYMIZE_FIELDS)


def resolve_export_fields(requested_fields: List[str]) -> List[str]:
    return resolve_export_fields_impl(requested_fields, EXPORT_FIELD_ORDER, EXPORT_DEFAULT_FIELDS)


def resolve_csv_anonymize_fields(requested_fields: List[str], enabled: bool) -> List[str]:
    return resolve_csv_anonymize_fields_impl(
        requested_fields,
        enabled,
        ANONYMIZE_FIELD_ORDER,
        ANONYMIZE_DEFAULT_FIELDS,
    )


def sanitize_filename(value: str, fallback: str = "export") -> str:
    return sanitize_filename_impl(value, fallback)


def format_patient_name(value: Optional[object]) -> str:
    return format_patient_name_impl(value)


def is_radiopharm_modality(modality: Optional[object]) -> bool:
    return is_radiopharm_modality_impl(modality)


def format_number_with_unit(value: Optional[object], unit: Optional[str], decimals: int) -> str:
    parsed = parse_db_float(value)
    if parsed is None:
        return ""
    formatted = f"{parsed:.{decimals}f}"
    return f"{formatted} {unit}".strip() if unit else formatted


def format_injected_activity(value: Optional[object], unit_value: Optional[object]) -> str:
    parsed = parse_db_float(value)
    if parsed is None:
        return ""
    unit_text = str(unit_value).strip() if unit_value else ""
    if unit_text:
        return f"{parsed:.2f} {unit_text}".strip()
    if parsed > 1e6:
        return f"{parsed / 1e6:.2f} MBq"
    return f"{parsed:.2f} MBq"


def format_total_dose(value: Optional[object]) -> str:
    parsed = parse_db_float(value)
    if parsed is None:
        return ""
    if parsed > 1e6:
        return f"{parsed / 1e6:.2f} MBq"
    return f"{parsed:.2f} MBq"


def format_dose_per_kg(value: Optional[float]) -> str:
    if value is None:
        return ""
    return f"{value:.2f} MBq/kg"


def format_export_value(field_name: str, row_dict: dict) -> str:
    return format_export_value_impl(
        field_name,
        row_dict,
        export_date_fields=EXPORT_DATE_FIELDS,
        export_time_fields=EXPORT_TIME_FIELDS,
        export_numeric_formats=EXPORT_NUMERIC_FORMATS,
    )


def anonymize_export_value(
    field_name: str,
    row_dict: dict,
    anonymize_fields: Set[str],
    anonymize_cache: Dict[Tuple[str, str], str],
    anonymize_counts: Dict[str, int],
) -> str:
    return anonymize_export_value_impl(
        field_name,
        row_dict,
        anonymize_fields,
        anonymize_cache,
        anonymize_counts,
        anonymize_blank_fields=ANONYMIZE_BLANK_FIELDS,
        export_date_fields=EXPORT_DATE_FIELDS,
        export_time_fields=EXPORT_TIME_FIELDS,
        export_numeric_formats=EXPORT_NUMERIC_FORMATS,
    )


def _resolve_export_query_fields(
    selected_fields: List[str],
    existing_columns: Optional[Set[str]] = None,
) -> Tuple[List[str], List[str], bool]:
    return resolve_export_query_fields_impl(
        selected_fields,
        EXPORT_DERIVED_FIELDS,
        EXPORT_DERIVED_DEPENDENCIES,
        existing_columns,
    )


def _write_csv_export_rows(
    writer: csv.writer,
    rows: List[sqlite3.Row],
    selected_fields: List[str],
    csv_anonymize_fields: Set[str],
    *,
    study_info: Optional[dict] = None,
    sectioned: bool = False,
    suppress_repeats: bool = False,
) -> None:
    return write_csv_export_rows_impl(
        writer,
        rows,
        selected_fields,
        csv_anonymize_fields,
        export_group_clear_fields=EXPORT_GROUP_CLEAR_FIELDS,
        anonymize_blank_fields=ANONYMIZE_BLANK_FIELDS,
        export_date_fields=EXPORT_DATE_FIELDS,
        export_time_fields=EXPORT_TIME_FIELDS,
        export_numeric_formats=EXPORT_NUMERIC_FORMATS,
        study_info=study_info,
        sectioned=sectioned,
        suppress_repeats=suppress_repeats,
    )


def _generate_anonymized_value(field_name: str, index: int) -> str:
    return generate_anonymized_value_impl(field_name, index)


def _anonymize_column(conn: sqlite3.Connection, field_name: str) -> int:
    # Replace each row independently to avoid deterministic one-to-one mapping
    # for repeated source values in a single export.
    cursor = conn.execute(
        f"""
        SELECT id
        FROM dicom_metadata
        WHERE "{field_name}" IS NOT NULL
          AND TRIM(CAST("{field_name}" AS TEXT)) != ''
        """
    )
    row_ids = [int(row[0]) for row in cursor.fetchall()]
    if not row_ids:
        return 0

    replacements = [
        (_generate_anonymized_value(field_name, idx), row_id)
        for idx, row_id in enumerate(row_ids, start=1)
    ]
    conn.executemany(
        f'UPDATE dicom_metadata SET "{field_name}" = ? WHERE id = ?',
        replacements
    )
    return len(row_ids)


def _blank_column(conn: sqlite3.Connection, field_name: str) -> int:
    cursor = conn.execute(
        f"""
        UPDATE dicom_metadata
        SET "{field_name}" = NULL
        WHERE "{field_name}" IS NOT NULL
          AND TRIM(CAST("{field_name}" AS TEXT)) != ''
        """
    )
    return int(cursor.rowcount or 0)


def _anonymize_private_tag_file_path(conn: sqlite3.Connection) -> int:
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='private_tag'")
    if cursor.fetchone() is None:
        return 0
    update_cursor = conn.execute(
        """
        UPDATE private_tag
        SET file_path = NULL
        WHERE file_path IS NOT NULL
          AND TRIM(CAST(file_path AS TEXT)) != ''
        """
    )
    return int(update_cursor.rowcount or 0)


def _scrub_all_private_tag_payloads(conn: sqlite3.Connection) -> int:
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='private_tag'")
    if cursor.fetchone() is None:
        return 0
    scrub_cursor = conn.execute(
        """
        UPDATE private_tag
        SET value_text = NULL,
            value_num = NULL,
            value_json = NULL,
            value_hex = NULL,
            byte_len = NULL,
            value_hash = NULL,
            file_path = NULL
        WHERE value_text IS NOT NULL
           OR value_num IS NOT NULL
           OR value_json IS NOT NULL
           OR value_hex IS NOT NULL
           OR byte_len IS NOT NULL
           OR value_hash IS NOT NULL
           OR file_path IS NOT NULL
        """
    )
    return int(scrub_cursor.rowcount or 0)


@app.route('/databanks/create', methods=['POST'])
def create_databank():
    db_name = normalize_db_name(request.form.get('name'))
    db_path = resolve_db_path(db_name)

    if os.path.exists(db_path):
        return jsonify({'success': False, 'message': 'Databank already exists.'}), 409

    try:
        conn = init_database(db_path)
        conn.close()
        return jsonify({'success': True, 'name': db_name})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/databanks/rename', methods=['POST'])
def rename_databank():
    old_db_name = normalize_db_name(request.form.get("db"))
    new_db_name = normalize_db_name(request.form.get("new_name"))
    old_db_path = resolve_db_path(old_db_name)
    new_db_path = resolve_db_path(new_db_name)

    if not os.path.exists(old_db_path):
        return jsonify({"success": False, "message": "Databank not found."}), 404
    if old_db_name == new_db_name:
        return jsonify({"success": False, "message": "Choose a different databank name."}), 400
    if os.path.exists(new_db_path):
        return jsonify({"success": False, "message": "A databank with that name already exists."}), 409

    sidecars = [
        (old_db_path, new_db_path),
        (f"{old_db_path}-wal", f"{new_db_path}-wal"),
        (f"{old_db_path}-shm", f"{new_db_path}-shm"),
    ]
    try:
        os.replace(old_db_path, new_db_path)
        for old_sidecar, new_sidecar in sidecars[1:]:
            if os.path.exists(old_sidecar):
                os.replace(old_sidecar, new_sidecar)
        return jsonify({"success": True, "name": new_db_name})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _table_exists(conn: sqlite3.Connection, schema: str, table_name: str) -> bool:
    cursor = conn.execute(
        f"SELECT name FROM {_quote_identifier(schema)}.sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    )
    return cursor.fetchone() is not None


def _table_columns(conn: sqlite3.Connection, schema: str, table_name: str) -> List[str]:
    cursor = conn.execute(f"PRAGMA {_quote_identifier(schema)}.table_info({_quote_identifier(table_name)})")
    return [str(row[1]) for row in cursor.fetchall()]


def _delete_studies_from_connection(conn: sqlite3.Connection, study_uids: List[str]) -> dict:
    unique_study_uids = list(dict.fromkeys(uid.strip() for uid in study_uids if uid and uid.strip()))
    if not unique_study_uids:
        return {"deleted_metadata_rows": 0, "deleted_private_tag_rows": 0}
    placeholders = ", ".join(["?"] * len(unique_study_uids))
    private_rows = 0
    if _table_exists(conn, "main", "private_tag"):
        private_cursor = conn.execute(
            f"DELETE FROM private_tag WHERE study_instance_uid IN ({placeholders})",
            unique_study_uids,
        )
        private_rows = int(private_cursor.rowcount or 0)
    metadata_cursor = conn.execute(
        f"DELETE FROM dicom_metadata WHERE study_instance_uid IN ({placeholders})",
        unique_study_uids,
    )
    return {
        "deleted_metadata_rows": int(metadata_cursor.rowcount or 0),
        "deleted_private_tag_rows": private_rows,
    }


def _compact_sqlite_database(conn: sqlite3.Connection) -> None:
    conn.execute("VACUUM")
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error:
        pass


def copy_studies_to_databank(source_db_path: str, target_db_path: str, study_uids: List[str]) -> dict:
    unique_study_uids = list(dict.fromkeys(uid.strip() for uid in study_uids if uid and uid.strip()))
    if not unique_study_uids:
        raise ValueError("No studies selected.")

    target_conn = init_database(target_db_path, optimize=False)
    try:
        target_conn.execute("ATTACH DATABASE ? AS source_db", (source_db_path,))
        placeholders = ", ".join(["?"] * len(unique_study_uids))
        source_count = target_conn.execute(
            f"""
            SELECT COUNT(DISTINCT study_instance_uid)
            FROM source_db.dicom_metadata
            WHERE study_instance_uid IN ({placeholders})
            """,
            unique_study_uids,
        ).fetchone()[0]
        if source_count == 0:
            raise ValueError("Selected studies were not found in the source databank.")

        target_cols = set(_table_columns(target_conn, "main", "dicom_metadata"))
        source_cols = _table_columns(target_conn, "source_db", "dicom_metadata")
        copy_cols = [col for col in source_cols if col != "id" and col in target_cols]
        if "study_instance_uid" not in copy_cols:
            raise ValueError("Source databank has no study UID column.")

        col_sql = ", ".join(_quote_identifier(col) for col in copy_cols)
        source_col_sql = ", ".join(f"source_db.dicom_metadata.{_quote_identifier(col)}" for col in copy_cols)
        before_changes = target_conn.total_changes
        target_conn.execute(
            f"""
            INSERT OR IGNORE INTO main.dicom_metadata ({col_sql})
            SELECT {source_col_sql}
            FROM source_db.dicom_metadata
            WHERE source_db.dicom_metadata.study_instance_uid IN ({placeholders})
            """,
            unique_study_uids,
        )
        metadata_rows = target_conn.total_changes - before_changes

        private_rows = 0
        if _table_exists(target_conn, "main", "private_tag") and _table_exists(target_conn, "source_db", "private_tag"):
            target_private_cols = set(_table_columns(target_conn, "main", "private_tag"))
            source_private_cols = _table_columns(target_conn, "source_db", "private_tag")
            private_copy_cols = [col for col in source_private_cols if col != "id" and col in target_private_cols]
            if "study_instance_uid" in private_copy_cols:
                private_col_sql = ", ".join(_quote_identifier(col) for col in private_copy_cols)
                private_source_col_sql = ", ".join(
                    f"source_db.private_tag.{_quote_identifier(col)}" for col in private_copy_cols
                )
                before_private_changes = target_conn.total_changes
                target_conn.execute(
                    f"""
                    INSERT OR IGNORE INTO main.private_tag ({private_col_sql})
                    SELECT {private_source_col_sql}
                    FROM source_db.private_tag
                    WHERE source_db.private_tag.study_instance_uid IN ({placeholders})
                    """,
                    unique_study_uids,
                )
                private_rows = target_conn.total_changes - before_private_changes

        target_conn.commit()
        return {
            "study_count": int(source_count),
            "metadata_rows": int(metadata_rows),
            "private_tag_rows": int(private_rows),
        }
    finally:
        try:
            target_conn.execute("DETACH DATABASE source_db")
        except sqlite3.Error:
            pass
        target_conn.close()


def transfer_studies_between_databanks(
    source_db_path: str,
    target_db_path: str,
    study_uids: List[str],
    action: str,
) -> dict:
    if action not in {"copy", "move"}:
        raise ValueError("Choose copy or move.")
    result = copy_studies_to_databank(source_db_path, target_db_path, study_uids)
    if action == "move":
        source_conn = get_db_connection(source_db_path)
        try:
            delete_result = _delete_studies_from_connection(source_conn, study_uids)
            source_conn.commit()
            _compact_sqlite_database(source_conn)
            result.update(delete_result)
        finally:
            source_conn.close()
    return result


@app.route('/databanks/copy-studies', methods=['POST'])
def copy_studies_databank():
    source_db_name = normalize_db_name(request.form.get("db"))
    target_db_name = normalize_db_name(request.form.get("target_name"))
    source_db_path = resolve_db_path(source_db_name)
    target_db_path = resolve_db_path(target_db_name)
    study_uids = request.form.getlist("study_uids")
    action = request.form.get("action", "copy")
    target_exists = os.path.exists(target_db_path)

    if not os.path.exists(source_db_path):
        return jsonify({"success": False, "message": "Source databank not found."}), 404
    if source_db_name == target_db_name:
        return jsonify({"success": False, "message": "Choose a different databank name."}), 400

    try:
        result = transfer_studies_between_databanks(source_db_path, target_db_path, study_uids, action)
        return jsonify({"success": True, "name": target_db_name, "action": action, **result})
    except ValueError as exc:
        if not target_exists and os.path.exists(target_db_path):
            try:
                os.remove(target_db_path)
            except OSError:
                pass
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        if not target_exists and os.path.exists(target_db_path):
            try:
                os.remove(target_db_path)
            except OSError:
                pass
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route('/databanks/export-anonymized')
def export_anonymized_databank():
    db_name = normalize_db_name(request.args.get("db"))
    db_path = resolve_db_path(db_name)
    if not os.path.exists(db_path):
        return f"Database not found: {db_path}", 404

    requested_fields = request.args.getlist("fields")
    requested_set = {name for name in requested_fields if name in ANONYMIZE_FIELD_ORDER}
    selected_set = set(ANONYMIZE_DEFAULT_FIELDS) | requested_set
    selected_fields = [name for name in ANONYMIZE_FIELD_ORDER if name in selected_set]

    fd, temp_path = tempfile.mkstemp(prefix="anonymized_", suffix=".db")
    os.close(fd)
    shutil.copy2(db_path, temp_path)

    conn = None
    try:
        conn = sqlite3.connect(temp_path)
        # Use rollback journal to avoid WAL sidecars in exported anonymized DB.
        conn.execute("PRAGMA journal_mode=DELETE")
        # Ensure deleted/updated bytes are actively zeroed before final rewrite.
        conn.execute("PRAGMA secure_delete=ON")
        cursor = conn.execute("PRAGMA table_info(dicom_metadata)")
        existing_columns: Set[str] = {str(row[1]) for row in cursor.fetchall()}
        applicable_fields = [field for field in selected_fields if field in existing_columns]
        for field_name in applicable_fields:
            if field_name in ANONYMIZE_BLANK_FIELDS:
                _blank_column(conn, field_name)
            else:
                _anonymize_column(conn, field_name)
        if "file_path" in applicable_fields:
            # Absolute path in UI is reconstructed from scan_root + file_path.
            # Scrub both sources so enabling file-path anonymization cannot leak names.
            if "scan_root" in existing_columns:
                _blank_column(conn, "scan_root")
            _anonymize_private_tag_file_path(conn)
        _scrub_all_private_tag_payloads(conn)
        conn.commit()
        # Repack database so old text is not recoverable via raw-page scanning tools.
        conn.execute("VACUUM")
    except Exception as exc:
        if conn is not None:
            conn.close()
        try:
            os.remove(temp_path)
        except OSError:
            pass
        return f"Failed to anonymize databank: {exc}", 500
    finally:
        if conn is not None:
            conn.close()

    @after_this_request
    def _cleanup_export_file(response):
        try:
            os.remove(temp_path)
        except OSError:
            pass
        return response

    export_name = sanitize_filename(f"{Path(db_name).stem}_anonymized") + ".db"
    return send_file(
        temp_path,
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name=export_name,
    )


def get_language():
    """Get current language from request or session, default to English."""
    request_lang = request.args.get('lang')
    if request_lang in {'en', 'de'}:
        return request_lang
    session_lang = session.get('language')
    if session_lang in {'en', 'de'}:
        return session_lang
    return 'en'


def get_translations():
    """Get translations for current language"""
    lang = get_language()
    return get_translation(lang)


@app.route('/TUMLogo.svg')
def tum_logo():
    """Serve the TUM logo asset."""
    return send_from_directory(os.path.dirname(__file__), "TUMLogo.svg", mimetype="image/svg+xml")


def get_db_connection(db_path=None):
    """Get database connection"""
    if db_path is None:
        db_path = DEFAULT_DB
    conn = init_database(db_path, optimize=False)
    conn.row_factory = sqlite3.Row
    return conn


def parse_float_arg(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def count_decimal_places(value: Optional[str]) -> int:
    if value is None:
        return 0
    value = value.strip()
    if not value:
        return 0
    if "." not in value:
        return 0
    return len(value.split(".", 1)[1])


def parse_db_float(value: Optional[object]) -> Optional[float]:
    """Coerce db values to float without throwing on non-numeric input."""
    return shared_parse_db_float(value)


def get_patient_weight(row_dict: dict) -> Optional[float]:
    """Return a usable patient weight, with a heuristic fallback."""
    return shared_get_patient_weight(row_dict)


def compute_delay_minutes(row_dict: dict) -> Optional[float]:
    return shared_compute_delay_minutes(row_dict)


def compute_dose_per_kg(row_dict: dict) -> Optional[float]:
    return shared_compute_dose_per_kg(row_dict)


def compute_delay_status(row_dict: dict) -> Tuple[Optional[float], str]:
    injection_time = row_dict.get('injection_time')
    acquisition_time = row_dict.get('acquisition_time')
    injection_date = row_dict.get('injection_date') or row_dict.get('study_date')
    acquisition_date = row_dict.get('acquisition_date') or row_dict.get('study_date')

    if not injection_time or not acquisition_time or not injection_date or not acquisition_date:
        return None, "missing"

    inj_date_str = str(injection_date).strip()
    acq_date_str = str(acquisition_date).strip()
    if len(inj_date_str) < 8 or len(acq_date_str) < 8:
        return None, "parse_fail"

    inj_time_parsed = parse_time_to_24hour(injection_time)
    acq_time_parsed = parse_time_to_24hour(acquisition_time)
    if not inj_time_parsed or not acq_time_parsed:
        return None, "parse_fail"

    try:
        inj_dt = datetime(
            int(inj_date_str[:4]), int(inj_date_str[4:6]), int(inj_date_str[6:8]),
            inj_time_parsed[0], inj_time_parsed[1], inj_time_parsed[2]
        )
        acq_dt = datetime(
            int(acq_date_str[:4]), int(acq_date_str[4:6]), int(acq_date_str[6:8]),
            acq_time_parsed[0], acq_time_parsed[1], acq_time_parsed[2]
        )
        delay_minutes = (acq_dt - inj_dt).total_seconds() / 60
    except Exception:
        return None, "parse_fail"

    if delay_minutes < 0:
        return delay_minutes, "negative"
    if delay_minutes > 240:
        return delay_minutes, "too_long"
    return delay_minutes, "ok"


def compute_dose_from_row(row_dict: dict) -> Tuple[Optional[float], Optional[float]]:
    return shared_compute_dose_from_row(row_dict)


def has_radiopharm(row_dict: dict) -> bool:
    return bool(row_dict.get("radiopharmaceutical"))


def has_time_conflict(row_dict: dict, tolerance_minutes: int = 120) -> bool:
    study_time = row_dict.get('study_time')
    series_time = row_dict.get('series_time')
    if not study_time or not series_time:
        return False
    study_seconds = parse_time_to_seconds(study_time)
    series_seconds = parse_time_to_seconds(series_time)
    if study_seconds is None or series_seconds is None:
        return False
    return abs((series_seconds - study_seconds) / 60) > tolerance_minutes


def select_study_representatives(rows):
    return shared_select_study_representatives(rows)


def load_representative_series(conn: sqlite3.Connection) -> Tuple[Dict[str, dict], List[dict]]:
    """Return representative series map and rows using the same query logic."""
    cursor = conn.execute("""
        WITH ranked AS (
            SELECT s.*, ROW_NUMBER() OVER (
                PARTITION BY s.series_instance_uid
                ORDER BY COALESCE(s.number_of_slices,0) DESC,
                         s.series_time IS NULL,
                         s.series_time ASC,
                         s.series_number IS NULL,
                         s.series_number ASC
            ) AS rn
            FROM dicom_metadata s
        )
        SELECT
            ranked.sop_instance_uid,
            ranked.series_instance_uid,
            ranked.study_instance_uid,
            ranked.modality,
            ranked.manufacturer,
            ranked.manufacturer_model_name,
            ranked.station_name,
            ranked.software_version,
            ranked.device_serial_number,
            ranked.series_description,
            ranked.number_of_slices,
            ranked.series_time,
            ranked.study_time,
            ranked.study_date,
            ranked.radiopharmaceutical,
            ranked.injection_date,
            ranked.injection_time,
            ranked.acquisition_date,
            ranked.acquisition_time,
            ranked.injected_activity,
            ranked.patient_weight,
            ranked.patient_size,
            ranked.patient_sex,
            ranked.patient_age,
            ranked.patient_birth_date,
            ranked.csa_image_header_hash,
            ranked.csa_series_header_hash,
            p.study_patient_weight
        FROM ranked
        LEFT JOIN (
            SELECT study_instance_uid, MAX(patient_weight) as study_patient_weight
            FROM dicom_metadata
            GROUP BY study_instance_uid
        ) p ON ranked.study_instance_uid = p.study_instance_uid
        WHERE rn = 1
    """)
    series_rows = [dict(row) for row in cursor.fetchall()]
    representative_map = select_study_representatives(series_rows)
    representative_series_rows = [entry["row"] for entry in representative_map.values()]
    return representative_map, representative_series_rows


def _load_private_tag_items(
    conn: sqlite3.Connection,
    series_uids: List[str],
    classification: str,
) -> Dict[str, List[dict]]:
    from dicom_browser.study_service import _load_private_tag_items as load_private_tag_items_impl

    return load_private_tag_items_impl(conn, series_uids, classification)


def resolve_display_path(scan_root: Optional[str], file_path: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    from dicom_browser.study_service import resolve_display_path as resolve_display_path_impl

    return resolve_display_path_impl(scan_root, file_path)


def fuzzy_match(text1, text2, threshold=0.6):
    """Calculate similarity between two strings (0.0 to 1.0)"""
    if not text1 or not text2:
        return 0.0
    text1 = str(text1).lower().strip()
    text2 = str(text2).lower().strip()

    # Exact match
    if text1 == text2:
        return 1.0

    # Contains match
    if text1 in text2 or text2 in text1:
        return 0.9

    # Sequence similarity
    return SequenceMatcher(None, text1, text2).ratio()


def build_search_query(search_term):
    """Build SQL query with case-insensitive fuzzy search"""
    search_term = search_term.strip()

    # Convert search term to lowercase for consistent case-insensitive matching
    search_term_lower = search_term.lower()

    # Escape special characters for LIKE queries (%, _) - use double backslash for SQL escape
    escaped_term = search_term_lower.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    search_like = f"%{escaped_term}%"

    # Build WHERE clause with OR conditions across multiple fields
    # Case-insensitive search using LOWER() on both field and pattern
    # SQLite LIKE is case-insensitive by default, but LOWER() ensures it for all databases
    where_clause = """
        WHERE (
            LOWER(f.patient_name) LIKE ? ESCAPE '\\' OR
            LOWER(f.patient_id) LIKE ? ESCAPE '\\' OR
            LOWER(f.modality) LIKE ? ESCAPE '\\' OR
            LOWER(f.study_description) LIKE ? ESCAPE '\\' OR
            LOWER(f.manufacturer) LIKE ? ESCAPE '\\' OR
            LOWER(f.radiopharmaceutical) LIKE ? ESCAPE '\\' OR
            LOWER(f.study_id) LIKE ? ESCAPE '\\' OR
            LOWER(f.accession_number) LIKE ? ESCAPE '\\'
        )
    """

    query = f"""
        WITH ranked AS (
            SELECT
                s.*,
                ROW_NUMBER() OVER (
                    PARTITION BY s.study_instance_uid, s.modality
                    ORDER BY
                        COALESCE(s.number_of_slices, 0) DESC,
                        s.series_time IS NULL,
                        s.series_time ASC,
                        s.series_number IS NULL,
                        s.series_number ASC
                ) AS rn
            FROM dicom_metadata s
        ),
        filtered AS (
            SELECT * FROM ranked WHERE rn = 1
        ),
        series_counts AS (
            SELECT
                study_instance_uid,
                COUNT(DISTINCT COALESCE(series_instance_uid, sop_instance_uid, file_path)) AS series_count
            FROM dicom_metadata
            GROUP BY study_instance_uid
        )
        SELECT
            f.study_instance_uid,
            MAX(f.patient_id) as patient_id,
            MAX(f.patient_name) as patient_name,
            MAX(f.study_date) as study_date,
            MAX(f.study_time) as study_time,
            MAX(f.study_description) as study_description,
            GROUP_CONCAT(DISTINCT f.modality) as modality,
            GROUP_CONCAT(DISTINCT f.manufacturer) as manufacturer,
            GROUP_CONCAT(DISTINCT f.radiopharmaceutical) as radiopharmaceutical,
            COALESCE(MAX(sc.series_count), 0) as series_count
        FROM filtered f
        LEFT JOIN series_counts sc ON sc.study_instance_uid = f.study_instance_uid
        {where_clause}
        GROUP BY f.study_instance_uid
        ORDER BY study_date DESC, study_time DESC
    """

    return query, [search_like] * 8


def _index_template_context(
    *,
    db_name: str,
    databanks: List[str],
    search_term: str,
    deleted: str,
    deleted_count: str,
    uptake_min: Optional[float],
    uptake_max: Optional[float],
    dose_min: Optional[float],
    dose_max: Optional[float],
    has_filters: bool,
    modality_filters: List[str],
    manufacturer_filters: List[str],
    radiopharmaceutical_filters: List[str],
    translations: dict,
    studies: Optional[List[dict]] = None,
    available_modalities: Optional[List[str]] = None,
    available_manufacturers: Optional[List[str]] = None,
    available_radiopharmaceuticals: Optional[List[str]] = None,
    error: Optional[str] = None,
) -> dict:
    return {
        "studies": studies or [],
        "db_name": db_name,
        "databanks": databanks,
        "error": error,
        "search_term": search_term,
        "deleted": deleted,
        "deleted_count": deleted_count,
        "uptake_min": uptake_min,
        "uptake_max": uptake_max,
        "dose_min": dose_min,
        "dose_max": dose_max,
        "has_filters": has_filters,
        "modality_filters": modality_filters,
        "available_modalities": available_modalities or [],
        "manufacturer_filters": manufacturer_filters,
        "available_manufacturers": available_manufacturers or [],
        "radiopharmaceutical_filters": radiopharmaceutical_filters,
        "available_radiopharmaceuticals": available_radiopharmaceuticals or [],
        "t": translations,
        "lang": get_language(),
    }


def _load_filter_options(conn: sqlite3.Connection) -> Tuple[List[str], List[str], List[str]]:
    cursor = conn.execute("""
        SELECT DISTINCT modality
        FROM dicom_metadata
        WHERE modality IS NOT NULL AND modality != ''
        ORDER BY modality
    """)
    available_modalities = [row[0] for row in cursor.fetchall()]

    cursor = conn.execute("""
        SELECT DISTINCT manufacturer
        FROM dicom_metadata
        WHERE manufacturer IS NOT NULL AND manufacturer != ''
        ORDER BY manufacturer
    """)
    available_manufacturers = [row[0] for row in cursor.fetchall()]

    cursor = conn.execute("""
        SELECT DISTINCT radiopharmaceutical
        FROM dicom_metadata
        WHERE radiopharmaceutical IS NOT NULL AND radiopharmaceutical != ''
        ORDER BY radiopharmaceutical
    """)
    available_radiopharmaceuticals = [row[0] for row in cursor.fetchall()]
    return available_modalities, available_manufacturers, available_radiopharmaceuticals


def _matches_range_filters(
    delay_minutes: Optional[float],
    dose_per_kg: Optional[float],
    uptake_min: Optional[float],
    uptake_max: Optional[float],
    dose_min: Optional[float],
    dose_max: Optional[float],
    uptake_max_precision: int,
    dose_max_precision: int,
) -> bool:
    if uptake_min is not None or uptake_max is not None:
        if delay_minutes is None:
            return False
        if uptake_min is not None and delay_minutes < uptake_min:
            return False
        if uptake_max is not None:
            compare_delay = round(delay_minutes, uptake_max_precision) if uptake_max_precision else delay_minutes
            if compare_delay > uptake_max:
                return False

    if dose_min is not None or dose_max is not None:
        if dose_per_kg is None:
            return False
        if dose_min is not None and dose_per_kg < dose_min:
            return False
        if dose_max is not None:
            compare_dose = round(dose_per_kg, dose_max_precision) if dose_max_precision else dose_per_kg
            if compare_dose > dose_max:
                return False

    return True


def _compute_filtered_study_uids(
    conn: sqlite3.Connection,
    *,
    has_filters: bool,
    qa_filters: bool,
    uptake_min: Optional[float],
    uptake_max: Optional[float],
    dose_min: Optional[float],
    dose_max: Optional[float],
    uptake_max_precision: int,
    dose_max_precision: int,
    missing: Optional[str],
    timing_issue: Optional[str],
    dose_issue: Optional[str],
    composition: Optional[str],
    qa_score: Optional[int],
) -> Optional[set]:
    if not has_filters:
        return None

    representative_map, representative_series_rows = load_representative_series(conn)
    filtered_study_uids = {
        entry["row"]["study_instance_uid"]
        for entry in representative_map.values()
        if _matches_range_filters(
            entry["delay_minutes"],
            entry["dose_per_kg"],
            uptake_min,
            uptake_max,
            dose_min,
            dose_max,
            uptake_max_precision,
            dose_max_precision,
        )
    }

    if not qa_filters:
        return filtered_study_uids

    representative_series_rows = [entry["row"] for entry in representative_map.values()]
    study_flags: Dict[str, dict] = {}
    study_modalities: Dict[str, set] = {}

    cursor = conn.execute("""
        SELECT
            study_instance_uid,
            GROUP_CONCAT(DISTINCT modality) as modalities
        FROM dicom_metadata
        GROUP BY study_instance_uid
    """)
    for row in cursor.fetchall():
        study_uid = row["study_instance_uid"]
        if not study_uid:
            continue
        study_modalities[study_uid] = set((row["modalities"] or "").split(","))

    for row in representative_series_rows:
        study_uid = row.get("study_instance_uid")
        if not study_uid:
            continue
        flags = study_flags.setdefault(study_uid, {
            "weight": False,
            "dose": False,
            "injection_time": False,
            "acquisition_time": False,
            "radiopharmaceutical": False,
            "patient_sex": False,
            "patient_age": False,
        })
        modality = row.get("modality") or ""
        study_modalities.setdefault(study_uid, set()).add(modality)
        if parse_db_float(row.get("patient_weight")) is not None:
            flags["weight"] = True
        if parse_db_float(row.get("injected_activity")) is not None:
            flags["dose"] = True
        if row.get("injection_time"):
            flags["injection_time"] = True
        if row.get("acquisition_time"):
            flags["acquisition_time"] = True
        if row.get("patient_sex"):
            flags["patient_sex"] = True
        if row.get("patient_age") or row.get("patient_birth_date"):
            flags["patient_age"] = True
        if is_radiopharm_modality(modality) and has_radiopharm(row):
            flags["radiopharmaceutical"] = True

    missing_study_uids = set()
    if missing:
        for study_uid, flags in study_flags.items():
            if missing in ("radiopharmaceutical", "dose", "injection_time"):
                modalities = study_modalities.get(study_uid, set())
                if not any(is_radiopharm_modality(m or "") for m in modalities):
                    continue
            if not flags.get(missing, False):
                missing_study_uids.add(study_uid)

    dose_values = []
    for row in representative_series_rows:
        modality = row.get("modality") or ""
        if not is_radiopharm_modality(modality):
            continue
        dose_per_kg, _ = compute_dose_from_row(row)
        if dose_per_kg is not None:
            dose_values.append(dose_per_kg)
    dose_mean = statistics.mean(dose_values) if dose_values else None
    dose_std = statistics.stdev(dose_values) if len(dose_values) > 1 else None

    csa_counts: Dict[str, int] = {}
    for row in representative_series_rows:
        fp = row.get("csa_series_header_hash")
        if fp:
            csa_counts[fp] = csa_counts.get(fp, 0) + 1
    majority_csa = max(csa_counts, key=csa_counts.get) if csa_counts else None

    qa_filtered_uids = set()
    for row in representative_series_rows:
        matches = True

        if missing and row.get("study_instance_uid") not in missing_study_uids:
            matches = False

        if timing_issue:
            _, status = compute_delay_status(row)
            if timing_issue == "study_time_conflict":
                if not has_time_conflict(row):
                    matches = False
            elif status != timing_issue:
                matches = False

        if dose_issue:
            modality = row.get("modality") or ""
            if not is_radiopharm_modality(modality):
                matches = False
            if not matches:
                continue
            dose_per_kg, _ = compute_dose_from_row(row)
            injected_activity = parse_db_float(row.get("injected_activity"))
            patient_weight = get_patient_weight(row)
            if dose_issue == "missing_activity" and not (patient_weight and injected_activity is None):
                matches = False
            elif dose_issue == "missing_weight" and not (injected_activity is not None and not patient_weight):
                matches = False
            elif dose_issue == "unit_mismatch":
                if dose_per_kg is None or (0.1 <= dose_per_kg <= 50):
                    matches = False
            elif dose_issue == "outlier":
                if dose_per_kg is None or dose_mean is None or not dose_std:
                    matches = False
                elif abs(dose_per_kg - dose_mean) <= 3 * dose_std:
                    matches = False

        if qa_score is not None:
            score = 0
            if parse_db_float(row.get("patient_weight")) is not None:
                score += 1
            if parse_db_float(row.get("injected_activity")) is not None:
                score += 1
            _, status = compute_delay_status(row)
            if status in ("ok", "too_long"):
                score += 1
            if status == "ok" and not has_time_conflict(row):
                score += 1
            if majority_csa and row.get("csa_series_header_hash") == majority_csa:
                score += 1
            if score != qa_score:
                matches = False

        if matches and row.get("study_instance_uid"):
            qa_filtered_uids.add(row["study_instance_uid"])

    if missing:
        qa_filtered_uids = missing_study_uids

    if composition:
        composition_uids = set()
        for study_uid, mods in study_modalities.items():
            series_count = 1
            if composition == "missing_ct" and "PT" in mods and "CT" not in mods:
                composition_uids.add(study_uid)
            elif composition == "missing_pt" and "CT" in mods and "PT" not in mods:
                composition_uids.add(study_uid)
            elif composition == "high_series" and series_count > 20:
                composition_uids.add(study_uid)
        qa_filtered_uids = qa_filtered_uids.intersection(composition_uids) if qa_filtered_uids else composition_uids

    if filtered_study_uids:
        return filtered_study_uids.intersection(qa_filtered_uids)
    return qa_filtered_uids


def _rank_search_results(studies: List[dict], search_term: str) -> List[dict]:
    search_lower = search_term.lower().strip()
    for study in studies:
        score = 0.0
        best_match_field = None
        fields_to_check = [
            ("patient_name", study.get("patient_name", "")),
            ("patient_id", study.get("patient_id", "")),
            ("modality", study.get("modality", "")),
            ("study_description", study.get("study_description", "")),
            ("manufacturer", study.get("manufacturer", "")),
            ("radiopharmaceutical", study.get("radiopharmaceutical", "")),
        ]

        for field_name, field_value in fields_to_check:
            if not field_value:
                continue
            field_lower = str(field_value).lower()
            if search_lower == field_lower:
                score = max(score, 1.0)
                best_match_field = field_name
            elif search_lower in field_lower:
                score = max(score, 0.95)
                if not best_match_field:
                    best_match_field = field_name
            elif field_lower in search_lower:
                score = max(score, 0.9)
                if not best_match_field:
                    best_match_field = field_name
            else:
                sim = fuzzy_match(search_lower, field_lower)
                if sim > score:
                    score = max(score, sim)
                    if sim >= 0.7:
                        best_match_field = field_name

        if score == 0.0:
            score = 0.5

        study["match_score"] = score
        study["match_field"] = best_match_field

    studies.sort(key=lambda x: x.get("match_score", 0), reverse=True)
    return studies


def _load_index_studies(conn: sqlite3.Connection, search_term: str) -> List[dict]:
    if search_term:
        query, params = build_search_query(search_term)
        cursor = conn.execute(query, params)
        studies = [dict(row) for row in cursor.fetchall()]
        return _rank_search_results(studies, search_term)

    cursor = conn.execute("""
        WITH ranked AS (
            SELECT
                s.*,
                ROW_NUMBER() OVER (
                    PARTITION BY s.study_instance_uid, s.modality
                    ORDER BY
                        COALESCE(s.number_of_slices, 0) DESC,
                        s.series_time IS NULL,
                        s.series_time ASC,
                        s.series_number IS NULL,
                        s.series_number ASC
                ) AS rn
            FROM dicom_metadata s
        ),
        series_counts AS (
            SELECT
                study_instance_uid,
                COUNT(DISTINCT COALESCE(series_instance_uid, sop_instance_uid, file_path)) AS series_count
            FROM dicom_metadata
            GROUP BY study_instance_uid
        )
        SELECT
            r.study_instance_uid,
            MAX(r.patient_id) as patient_id,
            MAX(r.patient_name) as patient_name,
            MAX(r.study_date) as study_date,
            MAX(r.study_time) as study_time,
            MAX(r.study_description) as study_description,
            GROUP_CONCAT(DISTINCT r.modality) as modality,
            GROUP_CONCAT(DISTINCT r.manufacturer) as manufacturer,
            GROUP_CONCAT(DISTINCT r.radiopharmaceutical) as radiopharmaceutical,
            COALESCE(MAX(sc.series_count), 0) as series_count
        FROM ranked r
        LEFT JOIN series_counts sc ON sc.study_instance_uid = r.study_instance_uid
        WHERE r.rn = 1
        GROUP BY r.study_instance_uid
        ORDER BY study_date DESC, study_time DESC
    """)
    return [dict(row) for row in cursor.fetchall()]


def _split_csv(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _apply_category_filters(
    studies: List[dict],
    modality_filters: List[str],
    manufacturer_filters: List[str],
    radiopharmaceutical_filters: List[str],
) -> List[dict]:
    if modality_filters:
        studies = [
            study for study in studies
            if set(_split_csv(study.get("modality"))).intersection(modality_filters)
        ]
    if manufacturer_filters:
        studies = [
            study for study in studies
            if set(_split_csv(study.get("manufacturer"))).intersection(manufacturer_filters)
        ]
    if radiopharmaceutical_filters:
        studies = [
            study for study in studies
            if set(_split_csv(study.get("radiopharmaceutical"))).intersection(radiopharmaceutical_filters)
        ]
    return studies


def _format_index_studies(studies: List[dict]) -> List[dict]:
    for study in studies:
        if study.get("study_date"):
            study["study_date_formatted"] = format_date(study["study_date"])
        if study.get("study_time"):
            study["study_time_formatted"] = format_time(study["study_time"])
        study["patient_name_display"] = format_patient_name(study.get("patient_name")) or None
    return studies


@app.route('/')
def index():
    """Main page - list all studies with optional search"""
    lang = request.args.get("lang")
    if lang and lang in ["en", "de"]:
        session["language"] = lang

    db_name = normalize_db_name(request.args.get("db"))
    db_path = resolve_db_path(db_name)
    search_term = request.args.get("search", "").strip()
    deleted = request.args.get("deleted", "0")
    deleted_count = request.args.get("count", "0")
    uptake_min = parse_float_arg(request.args.get("uptake_min"))
    uptake_max_raw = request.args.get("uptake_max")
    uptake_max = parse_float_arg(uptake_max_raw)
    dose_min = parse_float_arg(request.args.get("dose_min"))
    dose_max_raw = request.args.get("dose_max")
    dose_max = parse_float_arg(dose_max_raw)
    uptake_max_precision = count_decimal_places(uptake_max_raw)
    dose_max_precision = count_decimal_places(dose_max_raw)
    missing = request.args.get("missing")
    timing_issue = request.args.get("timing_issue")
    dose_issue = request.args.get("dose_issue")
    composition = request.args.get("composition")
    qa_score_raw = request.args.get("qa_score")
    qa_score = int(qa_score_raw) if qa_score_raw and qa_score_raw.isdigit() else None
    modality_filters = [m.strip() for m in request.args.getlist("modality") if m.strip()]
    manufacturer_filters = [m.strip() for m in request.args.getlist("manufacturer") if m.strip()]
    radiopharmaceutical_filters = [r.strip() for r in request.args.getlist("radiopharmaceutical") if r.strip()]
    qa_filters = any([missing, timing_issue, dose_issue, composition, qa_score is not None])
    has_filters = (
        any(v is not None for v in (uptake_min, uptake_max, dose_min, dose_max))
        or bool(modality_filters or manufacturer_filters or radiopharmaceutical_filters)
        or qa_filters
    )

    translations = get_translations()
    databanks = list_databanks()
    context = _index_template_context(
        db_name=db_name,
        databanks=databanks,
        search_term=search_term,
        deleted=deleted,
        deleted_count=deleted_count,
        uptake_min=uptake_min,
        uptake_max=uptake_max,
        dose_min=dose_min,
        dose_max=dose_max,
        has_filters=has_filters,
        modality_filters=modality_filters,
        manufacturer_filters=manufacturer_filters,
        radiopharmaceutical_filters=radiopharmaceutical_filters,
        translations=translations,
    )
    context["anonymize_fields"] = build_anonymize_fields(translations)
    context["export_sections"], _ = build_export_sections(translations)
    context["export_modalities"] = []

    if not os.path.exists(db_path):
        context["error"] = "Database not found"
        return render_template("index.html", **context)

    try:
        conn = get_db_connection(db_path)
        available_modalities, available_manufacturers, available_radiopharmaceuticals = _load_filter_options(conn)
        filtered_study_uids = _compute_filtered_study_uids(
            conn,
            has_filters=has_filters,
            qa_filters=qa_filters,
            uptake_min=uptake_min,
            uptake_max=uptake_max,
            dose_min=dose_min,
            dose_max=dose_max,
            uptake_max_precision=uptake_max_precision,
            dose_max_precision=dose_max_precision,
            missing=missing,
            timing_issue=timing_issue,
            dose_issue=dose_issue,
            composition=composition,
            qa_score=qa_score,
        )
        studies = _load_index_studies(conn, search_term)
        conn.close()

        if has_filters and filtered_study_uids is not None:
            studies = [s for s in studies if s["study_instance_uid"] in filtered_study_uids]
        studies = _apply_category_filters(
            studies,
            modality_filters,
            manufacturer_filters,
            radiopharmaceutical_filters,
        )
        studies = _format_index_studies(studies)

        context.update({
            "studies": studies,
            "available_modalities": available_modalities,
            "available_manufacturers": available_manufacturers,
            "available_radiopharmaceuticals": available_radiopharmaceuticals,
        })
        return render_template("index.html", **context)
    except (sqlite3.Error, ValueError, TypeError) as e:
        context["error"] = str(e)
        return render_template("index.html", **context)


def _build_study_detail_payload(conn: sqlite3.Connection, study_uid: str) -> Optional[dict]:
    return build_study_detail_payload_service(
        conn,
        study_uid,
        calculate_activity_at_scan=calculate_activity_at_scan,
    )


@app.route('/study/<study_uid>')
def study_detail(study_uid):
    """Study detail page - show all series in a study"""
    lang = request.args.get('lang')
    if lang and lang in ['en', 'de']:
        session['language'] = lang

    db_name = normalize_db_name(request.args.get('db'))
    db_path = resolve_db_path(db_name)
    translations = get_translations()
    export_sections, _ = build_export_sections(translations)
    databanks = list_databanks()

    if not os.path.exists(db_path):
        return f"Database not found: {db_path}", 404

    conn = None
    try:
        conn = get_db_connection(db_path)
        payload = _build_study_detail_payload(conn, study_uid)
        if not payload:
            return f"Study not found: {study_uid}", 404
        return render_template(
            'study_detail.html',
            study_info=payload["study_info"],
            series=payload["series"],
            db_name=db_name,
            databanks=databanks,
            export_sections=export_sections,
            export_modalities=payload["export_modalities"],
            anonymize_fields=build_anonymize_fields(translations),
            t=translations,
            lang=get_language(),
        )
    except (sqlite3.Error, ValueError, TypeError) as e:
        return f"Error: {str(e)}", 500
    finally:
        if conn is not None:
            conn.close()


@app.route('/study/<study_uid>/export.csv')
def export_study_csv(study_uid):
    """Export study metadata as CSV with selectable fields."""
    db_name = normalize_db_name(request.args.get('db'))
    db_path = resolve_db_path(db_name)

    if not os.path.exists(db_path):
        return f"Database not found: {db_path}", 404

    requested_fields = request.args.getlist('fields')
    selected_fields = resolve_export_fields(requested_fields)
    csv_anonymize_fields = set(resolve_csv_anonymize_fields(
        request.args.getlist('anonymize_field'),
        request.args.get('anonymize') == '1',
    ))
    group_mode = request.args.get('group')
    suppress_repeats = group_mode == 'modality'
    sectioned = group_mode == 'sectioned'

    translations = get_translations()
    _, label_map = build_export_sections(translations)
    conn = get_db_connection(db_path)
    export_fields, select_fields, _derived_selected = _resolve_export_query_fields(selected_fields)
    header = [label_map.get(name, name) for name in export_fields]
    select_exprs = [f"s.{field}" for field in select_fields] if select_fields else ["s.study_instance_uid"]
    column_list = ", ".join(select_exprs)
    modality_filters = [m.strip() for m in request.args.getlist('modality') if m.strip()]
    modality_clause = ""
    params: List[object] = [study_uid]
    if modality_filters:
        placeholders = ", ".join(["?"] * len(modality_filters))
        modality_clause = f" AND s.modality IN ({placeholders})"
        params.extend(modality_filters)
    cursor = conn.execute(
        f"""
        SELECT {column_list}
        FROM dicom_metadata s
        WHERE s.study_instance_uid = ?{modality_clause}
        ORDER BY series_number ASC, series_time ASC, series_instance_uid ASC
        """,
        params
    )
    rows = cursor.fetchall()

    cursor = conn.execute("""
        SELECT
            MAX(patient_weight) as patient_weight,
            MAX(patient_size) as patient_size,
            MAX(study_date) as study_date,
            MAX(study_time) as study_time
        FROM dicom_metadata
        WHERE study_instance_uid = ?
        GROUP BY study_instance_uid
    """, (study_uid,))
    study_info_row = cursor.fetchone()
    conn.close()
    study_info = dict(study_info_row) if study_info_row else {}

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(header)
    _write_csv_export_rows(
        writer,
        rows,
        export_fields,
        csv_anonymize_fields,
        study_info=study_info,
        sectioned=sectioned,
        suppress_repeats=suppress_repeats,
    )

    conn = get_db_connection(db_path)
    cursor = conn.execute(
        "SELECT MAX(patient_name) as patient_name FROM dicom_metadata WHERE study_instance_uid = ?",
        (study_uid,)
    )
    name_row = cursor.fetchone()
    conn.close()
    patient_name = format_patient_name(name_row["patient_name"]) if name_row else ""
    name_slug = sanitize_filename(patient_name) if patient_name else "patient"
    filename = sanitize_filename(f"{name_slug}_{study_uid}") + ".csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@app.route('/databanks/export.csv')
def export_databank_csv():
    """Export the whole databank as CSV with selectable fields."""
    db_name = normalize_db_name(request.args.get('db'))
    db_path = resolve_db_path(db_name)

    if not os.path.exists(db_path):
        return f"Database not found: {db_path}", 404

    translations = get_translations()
    _, label_map = build_export_sections(translations)
    selected_fields = resolve_export_fields(request.args.getlist('fields'))
    csv_anonymize_fields = set(resolve_csv_anonymize_fields(
        request.args.getlist('anonymize_field'),
        request.args.get('anonymize') == '1',
    ))

    conn = get_db_connection(db_path)
    try:
        cursor = conn.execute("PRAGMA table_info(dicom_metadata)")
        existing_columns = {str(row[1]) for row in cursor.fetchall()}
        export_fields, select_fields, _derived_selected = _resolve_export_query_fields(
            selected_fields,
            existing_columns,
        )
        select_exprs = [f'"{field}"' for field in select_fields] if select_fields else ['id']
        column_list = ", ".join(select_exprs)

        rows = conn.execute(
            f"""
            SELECT {column_list}
            FROM dicom_metadata
            ORDER BY study_date DESC, study_time DESC, study_instance_uid ASC, series_number ASC, series_time ASC, id ASC
            """
        ).fetchall()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([label_map.get(name, name) for name in export_fields])
        _write_csv_export_rows(writer, rows, export_fields, csv_anonymize_fields)
    finally:
        conn.close()

    filename = sanitize_filename(f"{Path(db_name).stem}_full_export") + ".csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@app.route('/study/<study_uid>/delete', methods=['POST'])
def delete_study(study_uid):
    """Delete a study and all its series from the database"""
    db_name = normalize_db_name(request.args.get('db'))
    db_path = resolve_db_path(db_name)

    if not os.path.exists(db_path):
        return f"Database not found: {db_path}", 404

    try:
        conn = get_db_connection(db_path)

        # Check if study exists
        cursor = conn.execute(
            "SELECT COUNT(*) FROM dicom_metadata WHERE study_instance_uid = ?",
            (study_uid,)
        )
        count = cursor.fetchone()[0]

        if count == 0:
            conn.close()
            return f"Study not found: {study_uid}", 404

        # Delete all series in this study
        delete_result = _delete_studies_from_connection(conn, [study_uid])
        deleted_count = delete_result["deleted_metadata_rows"]
        conn.commit()
        _compact_sqlite_database(conn)
        conn.close()

        # Redirect back to index page with success message
        from flask import redirect
        return redirect(f"/?db={db_name}&deleted=1&count={deleted_count}")

    except Exception as e:
        return f"Error deleting study: {str(e)}", 500


@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle ZIP/7Z file upload and process DICOM files"""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'message': 'No file provided'}), 400

        file = request.files['file']
        db_name = normalize_db_name(request.form.get('db'))
        db_path = resolve_db_path(db_name)

        if file.filename == '':
            return jsonify({'success': False, 'message': 'No file selected'}), 400

        # Check file extension
        filename = file.filename.lower()
        if not (filename.endswith('.zip') or filename.endswith('.7z')):
            return jsonify({'success': False, 'message': 'Only ZIP and 7Z files are supported'}), 400

        # Create temporary directory for extraction
        temp_dir = tempfile.mkdtemp(prefix='dicom_upload_')

        try:
            # Save uploaded file
            uploaded_path = os.path.join(temp_dir, file.filename)
            file.save(uploaded_path)

            # Extract archive into a temporary folder (cleaned up after processing)
            extract_dir = os.path.join(temp_dir, 'extracted')
            os.makedirs(extract_dir, exist_ok=True)

            if filename.endswith('.zip'):
                # Extract ZIP file
                with zipfile.ZipFile(uploaded_path, 'r') as zip_ref:
                    zip_ref.extractall(extract_dir)
            elif filename.endswith('.7z'):
                # Extract 7Z file - try py7zr first, fallback to system 7z command
                try:
                    import py7zr
                    with py7zr.SevenZipFile(uploaded_path, mode='r') as archive:
                        archive.extractall(extract_dir)
                except ImportError:
                    # Fallback to system 7z command if py7zr not available
                    import subprocess
                    result = subprocess.run(
                        ['7z', 'x', uploaded_path, '-o' + extract_dir, '-y'],
                        capture_output=True,
                        text=True
                    )
                    if result.returncode != 0:
                        return jsonify({
                            'success': False,
                            'message': 'Failed to extract 7Z file. Install py7zr (pip install py7zr) or system 7z command.'
                        }), 400

            # Process extracted DICOM files using existing process_directory function
            # This will handle all the processing, deduplication, and counting
            try:
                process_directory(
                    extract_dir,
                    db_path=db_path,
                    process_subdirs=True,
                    auto_workers=True,
                    scan_root_label=f"zip:{Path(file.filename).name}",
                )

                return jsonify({
                    'success': True,
                    'message': 'Archive processed successfully. Check the studies list below.'
                })

            except Exception as e:
                return jsonify({
                    'success': False,
                    'message': f'Error processing DICOM files: {str(e)}'
                }), 500

        finally:
            # Clean up temporary upload directory
            try:
                shutil.rmtree(temp_dir)
            except Exception as e:
                print(f"Warning: Failed to clean up temp directory {temp_dir}: {e}")

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Upload error: {str(e)}'
        }), 500


def _build_dashboard_payload(
    study_summary: List[dict],
    study_modalities: Dict[str, set],
    representative_series_rows: List[dict],
    db_path: str,
) -> dict:
    return build_dashboard_payload_service(
        study_summary=study_summary,
        study_modalities=study_modalities,
        representative_series_rows=representative_series_rows,
        db_path=db_path,
        parse_time_to_24hour=parse_time_to_24hour,
        calculate_injection_delay=calculate_injection_delay,
        compute_delay_status=compute_delay_status,
        has_time_conflict=has_time_conflict,
        has_radiopharm=has_radiopharm,
    )


@app.route('/dashboard')
def dashboard():
    """Analytics dashboard showing protocol adherence and distributions"""
    lang = request.args.get('lang')
    if lang and lang in ['en', 'de']:
        session['language'] = lang

    db_name = normalize_db_name(request.args.get('db'))
    db_path = resolve_db_path(db_name)
    translations = get_translations()
    databanks = list_databanks()

    if not os.path.exists(db_path):
        return f"Database not found: {db_path}", 404

    conn = None
    try:
        conn = get_db_connection(db_path)
        cursor = conn.execute("""
            SELECT
                study_instance_uid,
                MAX(patient_name) as patient_name,
                MAX(patient_sex) as patient_sex,
                MAX(patient_age) as patient_age,
                MAX(patient_birth_date) as patient_birth_date,
                MAX(patient_weight) as patient_weight,
                MAX(patient_size) as patient_size,
                MAX(study_date) as study_date,
                MAX(study_time) as study_time,
                MAX(study_description) as study_description,
                MAX(ctp_collection) as ctp_collection,
                MAX(ctp_subject_id) as ctp_subject_id,
                MAX(ctp_private_flag_raw) as ctp_private_flag_raw,
                MAX(ctp_private_flag_int) as ctp_private_flag_int
            FROM dicom_metadata
            GROUP BY study_instance_uid
        """)
        study_summary = [dict(row) for row in cursor.fetchall()]

        cursor = conn.execute("""
            SELECT
                study_instance_uid,
                GROUP_CONCAT(DISTINCT modality) as modalities
            FROM dicom_metadata
            GROUP BY study_instance_uid
        """)
        study_modalities = {
            row["study_instance_uid"]: set((row["modalities"] or "").split(","))
            for row in cursor.fetchall()
            if row["study_instance_uid"]
        }
        _representative_map, representative_series_rows = load_representative_series(conn)
        conn.close()
        conn = None

        payload = _build_dashboard_payload(
            study_summary=study_summary,
            study_modalities=study_modalities,
            representative_series_rows=representative_series_rows,
            db_path=db_path,
        )
        return render_template(
            'dashboard.html',
            db_name=db_name,
            databanks=databanks,
            t=translations,
            lang=get_language(),
            **payload,
        )
    except (sqlite3.Error, ValueError, TypeError) as e:
        return f"Error: {str(e)}", 500
    finally:
        if conn is not None:
            conn.close()


@app.route('/api/series/<series_uid>')
def series_detail(series_uid):
    """API endpoint to get detailed series information"""
    db_name = normalize_db_name(request.args.get('db'))
    db_path = resolve_db_path(db_name)

    if not os.path.exists(db_path):
        return jsonify({"error": "Database not found"}), 404

    try:
        conn = get_db_connection(db_path)
        cursor = conn.execute("""
            SELECT * FROM dicom_metadata
            WHERE series_instance_uid = ?
        """, (series_uid,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return jsonify({"error": "Series not found"}), 404

        return jsonify(dict(row))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def parse_time_to_24hour(time_str):
    """Parse time string and convert to 24-hour format, handling 12-hour format errors

    Returns: (hour, minute, second) tuple in 24-hour format, or None if parsing fails
    """
    return shared_parse_time_to_24hour(time_str)


def parse_time_to_seconds(time_str):
    """Convert DICOM time (HHMMSS.frac) to seconds since midnight"""
    if not time_str:
        return None
    try:
        time_str = str(time_str).strip()
        if len(time_str) >= 6:
            hours = int(time_str[:2])
            minutes = int(time_str[2:4])
            seconds = int(time_str[4:6])
            total_seconds = hours * 3600 + minutes * 60 + seconds

            # Add fractional part if present (DICOM fractions are decimal, not whole seconds)
            if '.' in time_str:
                frac_str = time_str.split('.', 1)[1]
                if frac_str:
                    total_seconds += float("0." + frac_str)

            return total_seconds
    except Exception:
        return None


def parse_date_to_days(date_str):
    """Convert DICOM date (YYYYMMDD) to days since epoch for calculations"""
    if not date_str or len(date_str) < 8:
        return None
    try:
        year = int(date_str[:4])
        month = int(date_str[4:6])
        day = int(date_str[6:8])
        dt = datetime(year, month, day)
        return (dt - datetime(1970, 1, 1)).days
    except Exception:
        return None


def calculate_patient_age(birth_date, study_date):
    """Calculate patient age in years from birth date and study date"""
    if not birth_date or not study_date:
        return None

    try:

        birth_str = str(birth_date).strip()
        study_str = str(study_date).strip()

        if len(birth_str) >= 8 and len(study_str) >= 8:
            birth_dt = datetime(int(birth_str[:4]), int(birth_str[4:6]), int(birth_str[6:8]))
            study_dt = datetime(int(study_str[:4]), int(study_str[4:6]), int(study_str[6:8]))

            age = (study_dt - birth_dt).days / 365.25
            return age
    except Exception:
        return None


def calculate_activity_at_scan(injected_activity, half_life_seconds, delay_minutes):
    """Calculate remaining activity at time of scan (with decay)"""
    if not injected_activity or not half_life_seconds or not delay_minutes or half_life_seconds <= 0:
        return None

    try:
        # Activity = A0 * e^(-lambda * t)
        # where lambda = ln(2) / half_life
        lambda_decay = math.log(2) / half_life_seconds
        time_seconds = delay_minutes * 60
        remaining_activity = injected_activity * math.exp(-lambda_decay * time_seconds)
        return remaining_activity
    except Exception:
        return None


def format_date(date_str):
    """Format DICOM date (YYYYMMDD) to DD/MM/YYYY format"""
    return format_date_impl(date_str)


def format_time(time_str):
    """Format DICOM time (HHMMSS.frac) to human-readable format (HH:MM:SS)"""
    return format_time_impl(time_str)


def format_private_timestamp(value_text: Optional[object]) -> Optional[str]:
    """Best-effort formatting for private-tag timestamps."""
    return format_private_timestamp_impl(value_text)


def parse_pet_dose_report(xml_text: str) -> Optional[List[dict]]:
    return parse_pet_dose_report_impl(xml_text)


def calculate_injection_delay(injection_date, injection_time, acquisition_date, acquisition_time, injection_date_missing=False, study_time=None):
    """Calculate delay between injection and acquisition in minutes."""
    return calculate_injection_delay_impl(
        injection_date,
        injection_time,
        acquisition_date,
        acquisition_time,
        injection_date_missing=injection_date_missing,
        study_time=study_time,
    )


def format_delay(minutes):
    """Format delay in minutes to human-readable format"""
    return format_delay_impl(minutes)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    print(f"Starting DICOM Metadata Browser on http://127.0.0.1:{port}")
    print(f"Using database: {DEFAULT_DB}")
    app.run(debug=False, host='127.0.0.1', port=port)

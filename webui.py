#!/usr/bin/env python3
"""
Clean Web UI for DICOM Metadata Browser
"""

from flask import Flask, render_template, request, jsonify, session, send_from_directory, Response
import sqlite3
import math
from pathlib import Path
import os
import tempfile
import zipfile
import shutil
import csv
import io
import re
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from typing import Optional, List, Tuple, Dict
from process_dicom import process_directory
from store_metadata import init_database
from translations import get_translation

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
            {"name": "patient_sex", "label_key": "patient_sex"},
            {"name": "patient_age", "label_key": "patient_age"},
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
            {"name": "study_description", "label_key": "study_description"},
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
            {"name": "protocol_name", "label_key": "protocol_name"},
            {"name": "modality", "label_key": "modality", "default": True},
            {"name": "body_part_examined", "label_key": "body_part"},
        ],
    },
    {
        "key": "manufacturer",
        "label_key": "manufacturer_information",
        "fields": [
            {"name": "manufacturer", "label_key": "manufacturer"},
            {"name": "manufacturer_model_name", "label_key": "model"},
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
            {"name": "scanning_sequence", "label_key": "scanning_sequence"},
            {"name": "sequence_variant", "label_key": "sequence_variant"},
            {"name": "scan_options", "label_key": "scan_options"},
            {"name": "acquisition_type", "label_key": "acquisition_type"},
            {"name": "slice_thickness", "label_key": "slice_thickness"},
            {"name": "reconstruction_diameter", "label_key": "reconstruction_diameter"},
            {"name": "reconstruction_algorithm", "label_key": "reconstruction_algorithm"},
            {"name": "convolution_kernel", "label_key": "convolution_kernel"},
            {"name": "filter_type", "label_key": "filter_type"},
            {"name": "spiral_pitch_factor", "label_key": "spiral_pitch_factor"},
            {"name": "ctdivol", "label_key": "ctdivol"},
            {"name": "dlp", "label_key": "dlp"},
            {"name": "kvp", "label_key": "kvp"},
            {"name": "exposure_time", "label_key": "exposure_time"},
            {"name": "exposure", "label_key": "exposure"},
            {"name": "tube_current", "label_key": "tube_current"},
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
            {"name": "half_life", "label_key": "half_life"},
            {"name": "decay_correction", "label_key": "decay_correction"},
            {"name": "radiopharmaceutical_volume", "label_key": "radiopharmaceutical_volume"},
            {"name": "radionuclide_total_dose", "label_key": "radionuclide_total_dose"},
            {"name": "uptake_delay", "label_key": "uptake_delay"},
            {"name": "dose_per_kg", "label_key": "dose_per_kg"},
        ],
    },
    {
        "key": "image",
        "label_key": "image_information",
        "fields": [
            {"name": "image_type", "label_key": "image_type"},
            {"name": "pixel_spacing", "label_key": "pixel_spacing"},
            {"name": "image_orientation_patient", "label_key": "image_orientation_patient"},
            {"name": "slice_location", "label_key": "slice_location"},
            {"name": "number_of_frames", "label_key": "number_of_frames"},
            {"name": "frame_time", "label_key": "frame_time"},
            {"name": "number_of_slices", "label_key": "number_of_slices"},
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

RADIOPHARM_MODALITIES = {
    "PT",  # PET
    "PET",
    "NM",  # Nuclear medicine/SPECT
    "SPECT",
    "NM/CT",
    "PET/CT",
    "SPECT/CT",
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
    sections = []
    label_map = {}
    for section in EXPORT_SECTIONS:
        section_label = translations.get(
            section.get("label_key"),
            str(section.get("label_key", section.get("key", ""))).replace("_", " ").title()
        )
        fields = []
        for field in section["fields"]:
            field_name = field["name"]
            label_key = field.get("label_key", field_name)
            label = translations.get(label_key, label_key.replace("_", " ").title())
            label_map[field_name] = label
            fields.append({
                "name": field_name,
                "label": label,
                "default": field.get("default", False),
            })
        sections.append({
            "key": section["key"],
            "label": section_label,
            "fields": fields,
        })
    return sections, label_map


def sanitize_filename(value: str, fallback: str = "export") -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value or "").strip("._")
    return safe or fallback


def format_patient_name(value: Optional[object]) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    parts = [part for part in text.split("^") if part]
    if len(parts) >= 2 and parts[0].lower() == "anonymous":
        return f"{parts[0]} {parts[1]}".strip()
    return " ".join(parts) if parts else text


def is_radiopharm_modality(modality: Optional[object]) -> bool:
    if not modality:
        return False
    value = str(modality).strip().upper()
    return value in RADIOPHARM_MODALITIES


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
    value = row_dict.get(field_name)
    if value is None:
        return ""
    if field_name == "patient_name":
        return format_patient_name(value)
    if field_name in EXPORT_DATE_FIELDS:
        return format_date(str(value))
    if field_name in EXPORT_TIME_FIELDS:
        return format_time(value)
    if field_name == "injected_activity":
        return format_injected_activity(value, row_dict.get("injected_activity_unit"))
    if field_name == "radionuclide_total_dose":
        return format_total_dose(value)
    if field_name == "uptake_delay":
        precomputed_delay = row_dict.get("uptake_delay") or row_dict.get("injection_delay")
        if precomputed_delay:
            return str(precomputed_delay)
        fallback_date = (
            row_dict.get("study_date")
            or row_dict.get("acquisition_date")
            or row_dict.get("series_date")
        )
        injection_date = (
            row_dict.get("injection_date")
            or row_dict.get("modality_injection_date")
            or fallback_date
        )
        acquisition_date = (
            row_dict.get("acquisition_date")
            or row_dict.get("modality_acquisition_date")
            or fallback_date
        )
        injection_time = (
            row_dict.get("injection_time")
            or row_dict.get("modality_injection_time")
        )
        acquisition_time = (
            row_dict.get("acquisition_time")
            or row_dict.get("series_time")
        )
        if injection_date and acquisition_date and injection_time and acquisition_time:
            delay_minutes, _ = calculate_injection_delay(
                injection_date,
                injection_time,
                acquisition_date,
                acquisition_time,
                injection_date_missing=(row_dict.get("injection_date") is None),
                study_time=row_dict.get("study_time")
            )
            if delay_minutes and delay_minutes > 0:
                return format_delay(delay_minutes)
        return ""
    if field_name == "dose_per_kg":
        precomputed_dose = row_dict.get("dose_per_kg") or row_dict.get("activity_per_kg")
        if isinstance(precomputed_dose, (int, float)):
            return format_dose_per_kg(float(precomputed_dose))
        if precomputed_dose:
            return str(precomputed_dose)
        patient_weight = get_patient_weight(row_dict)
        injected_activity = parse_db_float(row_dict.get("injected_activity"))
        if patient_weight and injected_activity:
            activity_mbq = injected_activity / 1e6 if injected_activity > 1e6 else injected_activity
            dose_per_kg = activity_mbq / patient_weight
            if 0 < dose_per_kg < 100:
                return format_dose_per_kg(dose_per_kg)
        return ""
    if field_name == "bmi":
        patient_weight = parse_db_float(
            row_dict.get("patient_weight") or row_dict.get("study_patient_weight")
        )
        patient_size = parse_db_float(
            row_dict.get("patient_size") or row_dict.get("study_patient_size")
        )
        if patient_weight and patient_size and patient_size > 0:
            bmi = patient_weight / (patient_size * patient_size)
            return f"{bmi:.1f}"
        return ""
    if field_name in EXPORT_NUMERIC_FORMATS:
        unit, decimals = EXPORT_NUMERIC_FORMATS[field_name]
        return format_number_with_unit(value, unit, decimals)
    return str(value)


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


def get_language():
    """Get current language from session or request, default to English"""
    return session.get('language', request.args.get('lang', 'en'))


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
    if value is None:
        return None
    try:
        value = str(value).strip()
    except Exception:
        return None
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def get_patient_weight(row_dict: dict) -> Optional[float]:
    """Return a usable patient weight, with a heuristic fallback."""
    weight = parse_db_float(row_dict.get('patient_weight'))
    if weight is not None and weight > 0:
        return weight
    weight = parse_db_float(row_dict.get('study_patient_weight'))
    if weight is not None and weight > 0:
        return weight
    size_value = parse_db_float(row_dict.get('patient_size'))
    # Some datasets store weight in the size field; only accept kg-like values.
    if size_value is not None and size_value > 10 and size_value <= 500:
        return size_value
    return None


def compute_delay_minutes(row_dict: dict) -> Optional[float]:
    if (row_dict.get('injection_date') or row_dict.get('study_date')) and \
       row_dict.get('injection_time') and \
       (row_dict.get('acquisition_date') or row_dict.get('study_date')) and \
       row_dict.get('acquisition_time'):
        injection_date = row_dict.get('injection_date') or row_dict.get('study_date')
        acquisition_date = row_dict.get('acquisition_date') or row_dict.get('study_date')
        delay_minutes, _ = calculate_injection_delay(
            injection_date,
            row_dict['injection_time'],
            acquisition_date,
            row_dict['acquisition_time'],
            injection_date_missing=(row_dict.get('injection_date') is None)
        )
        if delay_minutes and delay_minutes > 0:
            return delay_minutes
    return None


def compute_dose_per_kg(row_dict: dict) -> Optional[float]:
    study_weight = parse_db_float(row_dict.get('study_patient_weight'))
    injected_activity = parse_db_float(row_dict.get('injected_activity'))
    if study_weight is None or study_weight <= 0 or injected_activity is None:
        return None
    activity_per_kg = injected_activity / study_weight
    dose_per_kg = activity_per_kg / 1e6 if activity_per_kg > 1e6 else activity_per_kg
    if 0 < dose_per_kg < 100:
        return dose_per_kg
    return None


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
        from datetime import datetime
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
    patient_weight = get_patient_weight(row_dict)
    injected_activity = parse_db_float(row_dict.get('injected_activity'))
    if not patient_weight or patient_weight <= 0 or injected_activity is None:
        return None, None
    activity_mbq = injected_activity / 1e6 if injected_activity > 1e6 else injected_activity
    dose_per_kg = activity_mbq / patient_weight if patient_weight else None
    return dose_per_kg, activity_mbq


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
    representatives = {}
    for row in rows:
        row_dict = dict(row)
        study_uid = row_dict.get('study_instance_uid')
        if not study_uid:
            continue
        delay_minutes = compute_delay_minutes(row_dict)
        dose_per_kg = compute_dose_per_kg(row_dict)
        score = 0
        if dose_per_kg is not None:
            score += 3
        if delay_minutes is not None:
            score += 2
        if is_radiopharm_modality(row_dict.get('modality') or ''):
            score += 1
        current = representatives.get(study_uid)
        if current is None or score > current["score"]:
            representatives[study_uid] = {
                "score": score,
                "row": row_dict,
                "delay_minutes": delay_minutes,
                "dose_per_kg": dose_per_kg
            }
    return representatives


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
            COUNT(*) as series_count
        FROM filtered f
        {where_clause}
        GROUP BY f.study_instance_uid
        ORDER BY study_date DESC, study_time DESC
    """
    
    return query, [search_like] * 8



@app.route('/')
def index():
    """Main page - list all studies with optional search"""
    # Handle language setting
    lang = request.args.get('lang')
    if lang and lang in ['en', 'de']:
        session['language'] = lang
    
    db_name = normalize_db_name(request.args.get('db'))
    db_path = resolve_db_path(db_name)
    search_term = request.args.get('search', '').strip()
    deleted = request.args.get('deleted', '0')
    deleted_count = request.args.get('count', '0')
    uptake_min = parse_float_arg(request.args.get('uptake_min'))
    uptake_max_raw = request.args.get('uptake_max')
    uptake_max = parse_float_arg(uptake_max_raw)
    dose_min = parse_float_arg(request.args.get('dose_min'))
    dose_max_raw = request.args.get('dose_max')
    dose_max = parse_float_arg(dose_max_raw)
    uptake_max_precision = count_decimal_places(uptake_max_raw)
    dose_max_precision = count_decimal_places(dose_max_raw)
    missing = request.args.get('missing')
    timing_issue = request.args.get('timing_issue')
    dose_issue = request.args.get('dose_issue')
    composition = request.args.get('composition')
    qa_score_raw = request.args.get('qa_score')
    qa_score = int(qa_score_raw) if qa_score_raw and qa_score_raw.isdigit() else None
    modality_filters = [m.strip() for m in request.args.getlist('modality') if m.strip()]
    manufacturer_filters = [m.strip() for m in request.args.getlist('manufacturer') if m.strip()]
    radiopharmaceutical_filters = [r.strip() for r in request.args.getlist('radiopharmaceutical') if r.strip()]
    qa_filters = any([missing, timing_issue, dose_issue, composition, qa_score is not None])
    has_filters = any(v is not None for v in (uptake_min, uptake_max, dose_min, dose_max)) or \
        bool(modality_filters or manufacturer_filters or radiopharmaceutical_filters) or \
        qa_filters
    
    translations = get_translations()
    databanks = list_databanks()
    
    if not os.path.exists(db_path):
        return render_template(
            'index.html',
            studies=[],
            db_name=db_name,
            databanks=databanks,
            error="Database not found",
            search_term=search_term,
            deleted=deleted,
            deleted_count=deleted_count,
            uptake_min=uptake_min,
            uptake_max=uptake_max,
            dose_min=dose_min,
            dose_max=dose_max,
            has_filters=has_filters,
            modality_filters=modality_filters,
            available_modalities=[],
            manufacturer_filters=manufacturer_filters,
            available_manufacturers=[],
            radiopharmaceutical_filters=radiopharmaceutical_filters,
            available_radiopharmaceuticals=[],
            t=translations,
            lang=get_language(),
        )
    
    try:
        conn = get_db_connection(db_path)
        filtered_study_uids = None
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

        if has_filters:
            representative_map, representative_series_rows = load_representative_series(conn)

            def matches_filters(delay_minutes: Optional[float], dose_per_kg: Optional[float]) -> bool:
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

            filtered_study_uids = set()
            for entry in representative_map.values():
                if matches_filters(entry["delay_minutes"], entry["dose_per_kg"]):
                    filtered_study_uids.add(entry["row"]["study_instance_uid"])

            if qa_filters:
                import statistics
                representative_series_rows = [entry["row"] for entry in representative_map.values()]

                study_flags = {}
                study_modalities = {}
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
                        "patient_age": False
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

                csa_counts = {}
                for row in representative_series_rows:
                    fp = row.get("csa_series_header_hash")
                    if fp:
                        csa_counts[fp] = csa_counts.get(fp, 0) + 1
                majority_csa = max(csa_counts, key=csa_counts.get) if csa_counts else None

                qa_filtered_uids = set()
                for row in representative_series_rows:
                    matches = True
                    if missing:
                        if row.get("study_instance_uid") not in missing_study_uids:
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
                    filtered_study_uids = filtered_study_uids.intersection(qa_filtered_uids)
                else:
                    filtered_study_uids = qa_filtered_uids
        
        if search_term:
            query, params = build_search_query(search_term)
            cursor = conn.execute(query, params)
            all_studies = [dict(row) for row in cursor.fetchall()]
            
            # Calculate match scores for ranking (but don't filter - SQL already found matches)
            search_lower = search_term.lower().strip()
            for study in all_studies:
                score = 0.0
                best_match_field = None
                
                fields_to_check = [
                    ('patient_name', study.get('patient_name', '')),
                    ('patient_id', study.get('patient_id', '')),
                    ('modality', study.get('modality', '')),
                    ('study_description', study.get('study_description', '')),
                    ('manufacturer', study.get('manufacturer', '')),
                    ('radiopharmaceutical', study.get('radiopharmaceutical', '')),
                ]
                
                for field_name, field_value in fields_to_check:
                    if field_value:
                        field_lower = str(field_value).lower()
                        # Exact match
                        if search_lower == field_lower:
                            score = max(score, 1.0)
                            best_match_field = field_name
                        # Contains match (SQL LIKE already found this, so this is likely)
                        elif search_lower in field_lower:
                            score = max(score, 0.95)
                            if not best_match_field:
                                best_match_field = field_name
                        elif field_lower in search_lower:
                            score = max(score, 0.9)
                            if not best_match_field:
                                best_match_field = field_name
                        # Fuzzy match for typo tolerance
                        else:
                            sim = fuzzy_match(search_lower, field_lower)
                            if sim > score:
                                score = max(score, sim)
                                if sim >= 0.7:  # Good fuzzy match
                                    best_match_field = field_name
                
                # If SQL found it but no good match, give it a baseline score
                if score == 0.0:
                    score = 0.5  # SQL found it, so it's a match, just not a great one
                
                study['match_score'] = score
                study['match_field'] = best_match_field
            
            # Sort by match score (best matches first)
            all_studies.sort(key=lambda x: x.get('match_score', 0), reverse=True)
            studies = all_studies
        else:
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
                    COUNT(*) as series_count
                FROM ranked r
                WHERE r.rn = 1
                GROUP BY r.study_instance_uid
                ORDER BY study_date DESC, study_time DESC
        """)
            studies = [dict(row) for row in cursor.fetchall()]
        
        conn.close()

        if has_filters:
            studies = [s for s in studies if s['study_instance_uid'] in filtered_study_uids]

        def _split_csv(value: Optional[str]) -> List[str]:
            if not value:
                return []
            return [part.strip() for part in str(value).split(',') if part.strip()]

        if modality_filters:
            studies = [
                study for study in studies
                if set(_split_csv(study.get('modality'))).intersection(modality_filters)
            ]
        if manufacturer_filters:
            studies = [
                study for study in studies
                if set(_split_csv(study.get('manufacturer'))).intersection(manufacturer_filters)
            ]
        if radiopharmaceutical_filters:
            studies = [
                study for study in studies
                if set(_split_csv(study.get('radiopharmaceutical'))).intersection(radiopharmaceutical_filters)
            ]

        # Format dates and times
        for study in studies:
            if study.get('study_date'):
                study['study_date_formatted'] = format_date(study['study_date'])
            if study.get('study_time'):
                study['study_time_formatted'] = format_time(study['study_time'])
            # Clean up patient name display (remove DICOM delimiter characters ^)
            if study.get('patient_name'):
                # DICOM PatientName format is often: Last^First^Middle^Prefix^Suffix
                # For anonymized data like "Anonymous^00039^^^", show it cleaner
                parts = study['patient_name'].split('^')
                # If it's anonymized format (Anonymous^number), show it cleanly
                if len(parts) >= 2 and parts[0].lower() == 'anonymous':
                    study['patient_name_display'] = f"{parts[0]} {parts[1]}" if parts[1] else parts[0]
                else:
                    # Try to construct a readable name from parts
                    name_parts = [p for p in parts if p]  # Remove empty parts
                    study['patient_name_display'] = ' '.join(name_parts) if name_parts else study['patient_name']
            else:
                study['patient_name_display'] = None
        
        return render_template(
            'index.html',
            studies=studies,
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
            available_modalities=available_modalities,
            manufacturer_filters=manufacturer_filters,
            available_manufacturers=available_manufacturers,
            radiopharmaceutical_filters=radiopharmaceutical_filters,
            available_radiopharmaceuticals=available_radiopharmaceuticals,
            t=translations,
            lang=get_language(),
        )
    except Exception as e:
        return render_template(
            'index.html',
            studies=[],
            db_name=db_name,
            databanks=databanks,
            error=str(e),
            search_term=search_term,
            deleted=deleted,
            deleted_count=deleted_count,
            uptake_min=uptake_min,
            uptake_max=uptake_max,
            dose_min=dose_min,
            dose_max=dose_max,
            has_filters=has_filters,
            modality_filters=modality_filters,
            available_modalities=[],
            manufacturer_filters=manufacturer_filters,
            available_manufacturers=[],
            radiopharmaceutical_filters=radiopharmaceutical_filters,
            available_radiopharmaceuticals=[],
            t=translations,
            lang=get_language(),
        )


@app.route('/study/<study_uid>')
def study_detail(study_uid):
    """Study detail page - show all series in a study"""
    # Handle language setting
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
    
    try:
        conn = get_db_connection(db_path)
        
        # Get study summary - aggregate patient info from all files in study
        # Use MAX() to get first non-null value for each field (works because same patient should have same values)
        cursor = conn.execute("""
            SELECT 
                study_instance_uid,
                MAX(patient_id) as patient_id,
                MAX(patient_name) as patient_name,
                MAX(patient_birth_date) as patient_birth_date,
                MAX(patient_sex) as patient_sex,
                MAX(patient_age) as patient_age,
                MAX(patient_weight) as patient_weight,
                MAX(patient_size) as patient_size,
                MAX(study_date) as study_date,
                MAX(study_time) as study_time,
                MAX(acquisition_date) as acquisition_date,
                MAX(acquisition_time) as acquisition_time,
                MAX(study_description) as study_description,
                MAX(study_id) as study_id,
                MAX(accession_number) as accession_number,
                MAX(referring_physician_name) as referring_physician_name,
                MAX(manufacturer) as manufacturer,
                MAX(manufacturer_model_name) as manufacturer_model_name,
                MAX(institution_name) as institution_name,
                MAX(ctp_collection) as ctp_collection,
                MAX(ctp_subject_id) as ctp_subject_id,
                MAX(ctp_private_flag_raw) as ctp_private_flag_raw,
                MAX(ctp_private_flag_int) as ctp_private_flag_int,
                MAX(csa_image_header_json) as csa_image_header_json,
                MAX(csa_series_header_json) as csa_series_header_json,
                MAX(csa_image_header_hash) as csa_image_header_hash,
                MAX(csa_series_header_hash) as csa_series_header_hash
            FROM dicom_metadata
            WHERE study_instance_uid = ?
            GROUP BY study_instance_uid
        """, (study_uid,))
        study_info = cursor.fetchone()
        
        if not study_info:
            conn.close()
            return f"Study not found: {study_uid}", 404
        
        study_info = dict(study_info)
        
        # Get representative series for this study (one per modality).
        cursor = conn.execute("""
            WITH ranked AS (
                SELECT
                    s.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY s.modality
                        ORDER BY
                            COALESCE(s.number_of_slices, 0) DESC,
                            s.series_time IS NULL,
                            s.series_time ASC,
                            s.series_number IS NULL,
                            s.series_number ASC
                    ) AS rn
                FROM dicom_metadata s
                WHERE s.study_instance_uid = ?
            )
            SELECT 
                series_instance_uid,
                series_number,
                series_description,
                series_date,
                series_time,
                modality,
                body_part_examined,
                protocol_name,
                acquisition_date,
                acquisition_time,
                patient_position,
                scanning_sequence,
                sequence_variant,
                scan_options,
                acquisition_type,
                injection_time,
                injection_date,
                injected_activity,
                radiopharmaceutical,
                half_life,
                decay_correction,
                radiopharmaceutical_volume,
                radionuclide_total_dose,
                image_type,
                pixel_spacing,
                slice_thickness,
                reconstruction_diameter,
                reconstruction_algorithm,
                convolution_kernel,
                filter_type,
                spiral_pitch_factor,
                ctdivol,
                dlp,
                manufacturer,
                manufacturer_model_name,
                software_version,
                station_name,
                csa_image_header_json,
                csa_series_header_json,
                csa_image_header_hash,
                csa_series_header_hash,
                private_payload_fingerprint,
                image_orientation_patient,
                slice_location,
                number_of_frames,
                frame_time,
                number_of_slices,
                file_path
            FROM ranked
            WHERE rn = 1
            ORDER BY series_number ASC, series_time ASC
        """, (study_uid,))
        series = [dict(row) for row in cursor.fetchall()]
        export_modalities = sorted({
            s.get('modality') for s in series if s.get('modality')
        })
        series_uids = [s.get("series_instance_uid") for s in series if s.get("series_instance_uid")]
        private_creators = {}
        pipeline_tags = {}
        rt_tags = {}
        if series_uids:
            placeholders = ",".join(["?"] * len(series_uids))
            cursor = conn.execute(
                f"""
                SELECT series_instance_uid, creator, COUNT(*) as tag_count
                FROM private_tag
                WHERE series_instance_uid IN ({placeholders})
                GROUP BY series_instance_uid, creator
                """,
                series_uids,
            )
            for row in cursor.fetchall():
                private_creators.setdefault(row["series_instance_uid"], {})[row["creator"]] = row["tag_count"]

            cursor = conn.execute(
                f"""
                SELECT series_instance_uid, creator, group_hex, element_hex, value_text, value_num, value_hex
                FROM private_tag
                WHERE series_instance_uid IN ({placeholders})
                  AND classification = 'pipeline_provenance'
                ORDER BY series_instance_uid, creator, group_hex, element_hex
                """,
                series_uids,
            )
            for row in cursor.fetchall():
                item = dict(row)
                raw_value = item.get("value_text")
                if raw_value is None and item.get("value_num") is not None:
                    raw_value = str(item["value_num"])
                formatted = format_private_timestamp(raw_value) if raw_value else None
                item["display_value"] = formatted or raw_value or item.get("value_hex")
                pipeline_tags.setdefault(item["series_instance_uid"], []).append(item)

            cursor = conn.execute(
                f"""
                SELECT series_instance_uid, creator, group_hex, element_hex, value_text, value_num, value_hex
                FROM private_tag
                WHERE series_instance_uid IN ({placeholders})
                  AND classification = 'rt_provenance'
                ORDER BY series_instance_uid, creator, group_hex, element_hex
                """,
                series_uids,
            )
            for row in cursor.fetchall():
                item = dict(row)
                raw_value = item.get("value_text")
                if raw_value is None and item.get("value_num") is not None:
                    raw_value = str(item["value_num"])
                formatted = format_private_timestamp(raw_value) if raw_value else None
                item["display_value"] = formatted or raw_value or item.get("value_hex")
                rt_tags.setdefault(item["series_instance_uid"], []).append(item)

            cursor = conn.execute(
                f"""
                SELECT series_instance_uid, value_text
                FROM private_tag
                WHERE series_instance_uid IN ({placeholders})
                  AND creator = 'SIEMENS CSA HEADER'
                  AND value_text LIKE '%<PetDoseReportData%'
                """,
                series_uids,
            )
            pet_dose_reports = {}
            for row in cursor.fetchall():
                entries = parse_pet_dose_report(row["value_text"])
                if entries:
                    pet_dose_reports[row["series_instance_uid"]] = entries
        
        conn.close()
        
        study_info = dict(study_info)
        
        # Format dates and times
        if study_info.get('study_date'):
            study_info['study_date_formatted'] = format_date(study_info['study_date'])
        if study_info.get('study_time'):
            study_info['study_time_formatted'] = format_time(study_info['study_time'])
        # Note: Acquisition date/time removed from study level - 
        # different series can have different acquisition times, 
        # so we show them per-series in the series table instead
        if study_info.get('patient_birth_date'):
            study_info['patient_birth_date_formatted'] = format_date(study_info['patient_birth_date'])
        
        # Clean up patient name display (remove DICOM delimiter characters ^)
        if study_info.get('patient_name'):
            parts = study_info['patient_name'].split('^')
            if len(parts) >= 2 and parts[0].lower() == 'anonymous':
                study_info['patient_name_display'] = f"{parts[0]} {parts[1]}" if parts[1] else parts[0]
            else:
                name_parts = [p for p in parts if p]  # Remove empty parts
                study_info['patient_name_display'] = ' '.join(name_parts) if name_parts else study_info['patient_name']
        else:
            study_info['patient_name_display'] = None
        
        # Calculate derived metrics (removed study-level nuclear medicine calculations)
        # Note: Nuclear medicine information is now per-series (see series loop below)
        
        # 5. BMI calculation (BMI = weight / height²)
        if study_info.get('patient_weight') and study_info.get('patient_size'):
            height_m = study_info['patient_size']
            if height_m and height_m > 0:
                bmi = study_info['patient_weight'] / (height_m * height_m)
                study_info['bmi'] = bmi
                study_info['height_cm'] = height_m * 100  # Convert to cm for display
        
        for s in series:
            creator_counts = private_creators.get(s.get("series_instance_uid"), {})
            s["private_creators"] = dict(sorted(creator_counts.items(), key=lambda x: x[1], reverse=True))
            s["pipeline_provenance"] = pipeline_tags.get(s.get("series_instance_uid"), [])
            s["rt_provenance"] = rt_tags.get(s.get("series_instance_uid"), [])
            s["pet_dose_report"] = pet_dose_reports.get(s.get("series_instance_uid"))
            if s.get('series_date'):
                s['series_date_formatted'] = format_date(s['series_date'])
            if s.get('series_time'):
                s['series_time_formatted'] = format_time(s['series_time'])
            if s.get('acquisition_date'):
                s['acquisition_date_formatted'] = format_date(s['acquisition_date'])
            if s.get('acquisition_time'):
                s['acquisition_time_formatted'] = format_time(s['acquisition_time'])
                
                # Check if acquisition time suggests next day
                if study_info.get('study_time') and s.get('acquisition_time'):
                    try:
                        study_hours = int(str(study_info['study_time'])[:2])
                        acq_hours = int(str(s['acquisition_time'])[:2])
                        # If study is late (>= 22:00) and acquisition is early (<= 06:00), likely next day
                        if study_hours >= 22 and acq_hours <= 6:
                            s['acquisition_likely_next_day'] = True
                    except:
                        pass
            if s.get('injection_date'):
                s['injection_date_formatted'] = format_date(s['injection_date'])
            if s.get('injection_time'):
                s['injection_time_formatted'] = format_time(s['injection_time'])
            
            # Calculate injection-to-acquisition delay for this series
            # Use study_date as fallback if injection_date is missing (injection usually same day as study)
            # Use acquisition_date as primary, study_date as fallback
            injection_date_to_use = s.get('injection_date') or study_info.get('study_date')
            acquisition_date_to_use = s.get('acquisition_date') or study_info.get('study_date')
            
            if (injection_date_to_use and s.get('injection_time') and 
                acquisition_date_to_use and s.get('acquisition_time')):
                delay_minutes, _ = calculate_injection_delay(
                    injection_date_to_use,
                    s['injection_time'],
                    acquisition_date_to_use,
                    s['acquisition_time'],
                    injection_date_missing=(s.get('injection_date') is None),
                    study_time=study_info.get('study_time')
                )
                if delay_minutes:
                    s['injection_delay'] = format_delay(delay_minutes)
                    s['injection_delay_minutes'] = delay_minutes
            
            # Calculate activity per kg body weight for this series
            if s.get('injected_activity') and study_info.get('patient_weight'):
                activity_per_kg = s['injected_activity'] / study_info['patient_weight']
                s['activity_per_kg'] = activity_per_kg
            
            # Calculate remaining activity at scan time for this series
            # Use the injection delay we calculated above
            if (s.get('injected_activity') and s.get('half_life') and 
                s.get('injection_delay_minutes')):
                # Convert injected_activity to Bq if it's in MBq (DICOM standard stores in MBq)
                # Values > 1e6 are already in Bq, values < 1e6 are in MBq
                injected_activity_bq = s['injected_activity']
                if injected_activity_bq < 1e6:
                    # Value is in MBq, convert to Bq
                    injected_activity_bq = injected_activity_bq * 1e6
                
                remaining_activity = calculate_activity_at_scan(
                    injected_activity_bq,
                    s['half_life'],
                    s['injection_delay_minutes']
                )
                if remaining_activity:
                    s['activity_at_scan'] = remaining_activity
                    if injected_activity_bq > 0:
                        decay_percent = (1 - remaining_activity / injected_activity_bq) * 100
                        s['decay_percent'] = decay_percent
        
        return render_template('study_detail.html', 
                             study_info=study_info, 
                             series=series,
                             db_name=db_name,
                             databanks=databanks,
                             export_sections=export_sections,
                             export_modalities=export_modalities,
                             t=translations,
                             lang=get_language())
    except Exception as e:
        return f"Error: {str(e)}", 500


@app.route('/study/<study_uid>/export.csv')
def export_study_csv(study_uid):
    """Export study metadata as CSV with selectable fields."""
    db_name = normalize_db_name(request.args.get('db'))
    db_path = resolve_db_path(db_name)

    if not os.path.exists(db_path):
        return f"Database not found: {db_path}", 404

    requested_fields = request.args.getlist('fields')
    selected_fields = [name for name in EXPORT_FIELD_ORDER if name in requested_fields]
    if not selected_fields:
        selected_fields = list(EXPORT_DEFAULT_FIELDS)
    group_mode = request.args.get('group')
    suppress_repeats = group_mode == 'modality'
    sectioned = group_mode == 'sectioned'

    translations = get_translations()
    _, label_map = build_export_sections(translations)
    header = [label_map.get(name, name) for name in selected_fields]

    conn = get_db_connection(db_path)
    derived_selected = any(field in EXPORT_DERIVED_FIELDS for field in selected_fields)
    extra_fields = sorted(EXPORT_DERIVED_DEPENDENCIES) if derived_selected else []
    real_fields = [field for field in selected_fields if field not in EXPORT_DERIVED_FIELDS]
    select_fields = list(dict.fromkeys(real_fields + extra_fields))
    select_exprs = [f"r.{field}" for field in select_fields] if select_fields else ["r.study_instance_uid"]
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
        WITH ranked AS (
            SELECT
                s.*,
                ROW_NUMBER() OVER (
                    PARTITION BY s.modality
                    ORDER BY
                        COALESCE(s.number_of_slices, 0) DESC,
                        s.series_time IS NULL,
                        s.series_time ASC,
                        s.series_number IS NULL,
                        s.series_number ASC
                ) AS rn
            FROM dicom_metadata s
            WHERE s.study_instance_uid = ?{modality_clause}
        )
        SELECT {column_list}
        FROM ranked r
        WHERE r.rn = 1
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
    last_group_values = {}
    if sectioned:
        patient_fields = [f for f in selected_fields if f in EXPORT_GROUP_CLEAR_FIELDS]
        if patient_fields:
            base_row = dict(rows[0]) if rows else {}
            base_row["study_patient_weight"] = study_info.get("patient_weight")
            base_row["study_patient_size"] = study_info.get("patient_size")
            patient_row = {name: "" for name in selected_fields}
            for name in patient_fields:
                if name == "bmi":
                    patient_weight = parse_db_float(base_row.get("study_patient_weight"))
                    patient_size = parse_db_float(base_row.get("study_patient_size"))
                    if patient_weight and patient_size and patient_size > 0:
                        patient_row[name] = f"{(patient_weight / (patient_size * patient_size)):.1f}"
                        continue
                patient_row[name] = format_export_value(name, base_row)
            writer.writerow([patient_row.get(name, "") for name in selected_fields])
            writer.writerow([])
    for index, row in enumerate(rows):
        row_dict = dict(row)
        row_dict["study_patient_weight"] = study_info.get("patient_weight")
        row_dict["study_patient_size"] = study_info.get("patient_size")
        if derived_selected:
            injection_date_to_use = row_dict.get("injection_date") or study_info.get("study_date")
            acquisition_date_to_use = row_dict.get("acquisition_date") or study_info.get("study_date")
            if (injection_date_to_use and row_dict.get("injection_time")
                    and acquisition_date_to_use and row_dict.get("acquisition_time")):
                delay_minutes, _ = calculate_injection_delay(
                    injection_date_to_use,
                    row_dict["injection_time"],
                    acquisition_date_to_use,
                    row_dict["acquisition_time"],
                    injection_date_missing=(row_dict.get("injection_date") is None),
                    study_time=study_info.get("study_time")
                )
                if delay_minutes:
                    row_dict["uptake_delay"] = format_delay(delay_minutes)
            injected_activity = parse_db_float(row_dict.get("injected_activity"))
            patient_weight = get_patient_weight(row_dict)
            if injected_activity and patient_weight:
                activity_mbq = injected_activity / 1e6 if injected_activity > 1e6 else injected_activity
                dose_per_kg = activity_mbq / patient_weight
                if 0 < dose_per_kg < 100:
                    row_dict["dose_per_kg"] = dose_per_kg
            patient_size = parse_db_float(
                row_dict.get("patient_size") or study_info.get("patient_size")
            )
            if patient_weight and patient_size and patient_size > 0:
                row_dict["bmi"] = patient_weight / (patient_size * patient_size)
        formatted_row = {name: format_export_value(name, row_dict) for name in selected_fields}
        if sectioned:
            for field_name in EXPORT_GROUP_CLEAR_FIELDS:
                if field_name in formatted_row:
                    formatted_row[field_name] = ""
        if suppress_repeats and index > 0:
            for field_name in EXPORT_GROUP_CLEAR_FIELDS:
                if field_name in formatted_row and formatted_row[field_name] == last_group_values.get(field_name):
                    formatted_row[field_name] = ""
        if index == 0:
            last_group_values = formatted_row.copy()
        writer.writerow([formatted_row.get(name, "") for name in selected_fields])

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
        cursor = conn.execute(
            "DELETE FROM dicom_metadata WHERE study_instance_uid = ?",
            (study_uid,)
        )
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()
        
        # Redirect back to index page with success message
        from flask import redirect, url_for
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
            
            # Extract archive
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
                            'message': f'Failed to extract 7Z file. Install py7zr (pip install py7zr) or system 7z command.'
                        }), 400
            
            # Process extracted DICOM files using existing process_directory function
            # This will handle all the processing, deduplication, and counting
            try:
                process_directory(
                    extract_dir,
                    db_path=db_path,
                    process_subdirs=True,
                    auto_workers=True,
                )
                
                # Get summary from database - count new files added
                conn = get_db_connection(db_path)
                cursor = conn.execute("SELECT COUNT(*) FROM dicom_metadata")
                total_files = cursor.fetchone()[0]
                conn.close()
                
                return jsonify({
                    'success': True,
                    'message': f'Archive processed successfully. Check the studies list below.'
                })
                
            except Exception as e:
                return jsonify({
                    'success': False,
                    'message': f'Error processing DICOM files: {str(e)}'
                }), 500
        
        finally:
            # Clean up temporary directory
            try:
                shutil.rmtree(temp_dir)
            except Exception as e:
                print(f"Warning: Failed to clean up temp directory {temp_dir}: {e}")
    
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Upload error: {str(e)}'
        }), 500


@app.route('/dashboard')
def dashboard():
    """Analytics dashboard showing protocol adherence and distributions"""
    # Handle language setting
    lang = request.args.get('lang')
    if lang and lang in ['en', 'de']:
        session['language'] = lang
    
    db_name = normalize_db_name(request.args.get('db'))
    db_path = resolve_db_path(db_name)
    translations = get_translations()
    databanks = list_databanks()
    
    if not os.path.exists(db_path):
        return f"Database not found: {db_path}", 404
    
    try:
        conn = get_db_connection(db_path)
        
        # Ideal values
        IDEAL_UPTAKE_TIME_MINUTES = 60  # 60 minutes ideal uptake time
        IDEAL_DOSE_PER_KG_MBQ = 3.0  # 3 MBq/kg ideal dose
        
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
        study_modalities_all = {
            row["study_instance_uid"]: set((row["modalities"] or "").split(","))
            for row in cursor.fetchall()
            if row["study_instance_uid"]
        }

        representative_map, representative_series_rows = load_representative_series(conn)
        conn.close()
        study_series_counts = {row.get("study_instance_uid"): 1 for row in representative_series_rows if row.get("study_instance_uid")}
        study_modalities = study_modalities_all
        
        # Process data and calculate metrics
        uptake_times = []
        doses_per_kg = []
        activities_mbq = []
        scan_durations = []
        radiopharmaceuticals = {}
        radiopharm_total_series = 0
        manufacturers = {}
        modality_stats = {}
        radiopharm_stats = {}
        ct_dose_by_modality = {}
        for row_dict in representative_series_rows:
            modality = row_dict.get('modality') or 'Unknown'
            radiopharm = row_dict.get('radiopharmaceutical') or 'Unknown'

            modality_bucket = modality_stats.setdefault(modality, {
                "count": 0,
                "uptake_times": [],
                "doses_per_kg": [],
                "missing_weight": 0,
                "missing_injection_time": 0,
                "missing_acquisition_time": 0
            })
            radiopharm_bucket = None
            if is_radiopharm_modality(modality):
                radiopharm_bucket = radiopharm_stats.setdefault(radiopharm, {
                    "count": 0,
                    "uptake_times": [],
                    "doses_per_kg": [],
                    "missing_weight": 0,
                    "missing_injection_time": 0,
                    "missing_acquisition_time": 0
                })
                radiopharm_bucket["count"] += 1
                radiopharm_total_series += 1
            modality_bucket["count"] += 1
            
            # Calculate uptake time (injection to acquisition delay)
            delay_minutes = None
            if (row_dict.get('injection_date') or row_dict.get('study_date')) and \
               row_dict.get('injection_time') and \
               (row_dict.get('acquisition_date') or row_dict.get('study_date')) and \
               row_dict.get('acquisition_time'):
                
                injection_date = row_dict.get('injection_date') or row_dict.get('study_date')
                acquisition_date = row_dict.get('acquisition_date') or row_dict.get('study_date')
                
                delay_minutes, _ = calculate_injection_delay(
                    injection_date,
                    row_dict['injection_time'],
                    acquisition_date,
                    row_dict['acquisition_time'],
                    injection_date_missing=(row_dict.get('injection_date') is None)
                )
                
                if delay_minutes and delay_minutes > 0:
                    uptake_times.append(delay_minutes)
                    modality_bucket["uptake_times"].append(delay_minutes)
                    if radiopharm_bucket is not None:
                        radiopharm_bucket["uptake_times"].append(delay_minutes)
            else:
                modality_bucket["missing_injection_time"] += 1
                if radiopharm_bucket is not None:
                    radiopharm_bucket["missing_injection_time"] += 1
            if not (row_dict.get('acquisition_time') and (row_dict.get('acquisition_date') or row_dict.get('study_date'))):
                modality_bucket["missing_acquisition_time"] += 1
                if radiopharm_bucket is not None:
                    radiopharm_bucket["missing_acquisition_time"] += 1
            
            # Calculate dose per kg
            patient_weight = get_patient_weight(row_dict)
            injected_activity = parse_db_float(row_dict.get('injected_activity'))
            dose_per_kg = None
            activity_mbq = None
            if patient_weight is not None and injected_activity is not None and patient_weight > 0:
                # Convert to MBq if needed (check if > 1e6, then it's in Bq)
                activity_mbq = injected_activity / 1e6 if injected_activity > 1e6 else injected_activity
                dose_per_kg = activity_mbq / patient_weight
                
                if dose_per_kg > 0 and dose_per_kg < 100:  # Reasonable range
                    doses_per_kg.append(dose_per_kg)
                    activities_mbq.append(activity_mbq)
                    modality_bucket["doses_per_kg"].append(dose_per_kg)
                    if radiopharm_bucket is not None:
                        radiopharm_bucket["doses_per_kg"].append(dose_per_kg)
                else:
                    dose_per_kg = None
            else:
                modality_bucket["missing_weight"] += 1
                if radiopharm_bucket is not None:
                    radiopharm_bucket["missing_weight"] += 1

            # Scan duration proxy
            series_time = row_dict.get('series_time')
            acquisition_time = row_dict.get('acquisition_time')
            if series_time and acquisition_time:
                series_seconds = parse_time_to_seconds(series_time)
                acquisition_seconds = parse_time_to_seconds(acquisition_time)
                if series_seconds is not None and acquisition_seconds is not None:
                    duration = (acquisition_seconds - series_seconds) / 60
                    if 0 <= duration <= 480:
                        scan_durations.append(duration)
            
            # Count radiopharmaceuticals
            if is_radiopharm_modality(modality) and row_dict.get('radiopharmaceutical'):
                rad = row_dict['radiopharmaceutical']
                radiopharmaceuticals[rad] = radiopharmaceuticals.get(rad, 0) + 1
            
            # Count manufacturers
            if row_dict.get('manufacturer'):
                mfr = row_dict['manufacturer']
                manufacturers[mfr] = manufacturers.get(mfr, 0) + 1

            # CT dose metrics per modality
            if row_dict.get('ctdivol') is not None or row_dict.get('dlp') is not None:
                ct_bucket = ct_dose_by_modality.setdefault(modality, {
                    "ctdivol": [],
                    "dlp": [],
                    "count": 0
                })
                if row_dict.get('ctdivol') is not None:
                    ct_bucket["ctdivol"].append(row_dict["ctdivol"])
                if row_dict.get('dlp') is not None:
                    ct_bucket["dlp"].append(row_dict["dlp"])
                ct_bucket["count"] += 1


        
        # Calculate statistics
        import statistics
        
        # Helper function to safely convert to float or None
        def safe_float(value):
            return float(value) if value is not None else None
        
        def safe_stats(values):
            if not values:
                return {
                    "count": 0,
                    "mean": None,
                    "median": None,
                    "std_dev": None,
                    "min": None,
                    "max": None,
                }
            return {
                "count": len(values),
                "mean": safe_float(statistics.mean(values)) if values else None,
                "median": safe_float(statistics.median(values)) if values else None,
                "std_dev": safe_float(statistics.stdev(values)) if len(values) > 1 else None,
                "min": safe_float(min(values)) if values else None,
                "max": safe_float(max(values)) if values else None,
            }

        total_series = len(representative_series_rows)
        total_studies = len(study_summary)

        redo_total = len(representative_series_rows)
        redo_with_repeats = 0

        def parse_age_years(value: Optional[object]) -> Optional[int]:
            if not value:
                return None
            text = str(value).strip()
            if not text:
                return None
            digits = "".join([c for c in text if c.isdigit()])
            if not digits:
                return None
            try:
                return int(digits)
            except ValueError:
                return None

        age_buckets = {
            "0-17": 0,
            "18-39": 0,
            "40-59": 0,
            "60-79": 0,
            "80+": 0
        }
        sex_counts = {}
        missing_weight = 0
        missing_height = 0
        missing_birth_date = 0
        ctp_flagged = 0
        study_dates = {}
        study_hours = {}
        for study in study_summary:
            sex = study.get("patient_sex") or "Unknown"
            sex_counts[sex] = sex_counts.get(sex, 0) + 1
            age_years = parse_age_years(study.get("patient_age"))
            if age_years is not None:
                if age_years <= 17:
                    age_buckets["0-17"] += 1
                elif age_years <= 39:
                    age_buckets["18-39"] += 1
                elif age_years <= 59:
                    age_buckets["40-59"] += 1
                elif age_years <= 79:
                    age_buckets["60-79"] += 1
                else:
                    age_buckets["80+"] += 1
            if parse_db_float(study.get("patient_weight")) is None:
                missing_weight += 1
            if parse_db_float(study.get("patient_size")) is None:
                missing_height += 1
            if not study.get("patient_birth_date"):
                missing_birth_date += 1
            if study.get("ctp_collection") or study.get("ctp_subject_id") or study.get("ctp_private_flag_raw") or study.get("ctp_private_flag_int") is not None:
                ctp_flagged += 1
            if study.get("study_date"):
                study_dates[study["study_date"]] = study_dates.get(study["study_date"], 0) + 1
            if study.get("study_time"):
                time_parsed = parse_time_to_24hour(study["study_time"])
                if time_parsed:
                    study_hours[time_parsed[0]] = study_hours.get(time_parsed[0], 0) + 1

        def summarize_group(group_data):
            results = {}
            for key, data in group_data.items():
                uptake = safe_stats(data["uptake_times"])
                dose = safe_stats(data["doses_per_kg"])
                results[key] = {
                    "count": data["count"],
                    "uptake_mean": uptake["mean"],
                    "uptake_median": uptake["median"],
                    "uptake_within": len([t for t in data["uptake_times"] if 45 <= t <= 75]),
                    "dose_mean": dose["mean"],
                    "dose_median": dose["median"],
                    "dose_within": len([d for d in data["doses_per_kg"] if 2.5 <= d <= 3.5]),
                    "missing_weight": data["missing_weight"],
                    "missing_injection_time": data["missing_injection_time"],
                    "missing_acquisition_time": data["missing_acquisition_time"],
                }
            return results

        modality_summary = summarize_group(modality_stats)
        radiopharm_summary = summarize_group(radiopharm_stats)
        missing_series_weight = sum(group["missing_weight"] for group in modality_stats.values())
        missing_series_injection = sum(group["missing_injection_time"] for group in modality_stats.values())
        missing_series_acquisition = sum(group["missing_acquisition_time"] for group in modality_stats.values())

        ct_summary = {}
        for modality, values in ct_dose_by_modality.items():
            ctdivol_stats = safe_stats(values["ctdivol"])
            dlp_stats = safe_stats(values["dlp"])
            ct_summary[modality] = {
                "count": values["count"],
                "ctdivol_mean": ctdivol_stats["mean"],
                "ctdivol_median": ctdivol_stats["median"],
                "dlp_mean": dlp_stats["mean"],
                "dlp_median": dlp_stats["median"],
            }

        stats = {
            'total_series': total_series,
            'total_studies': total_studies,
            'uptake_time': {
                'count': len(uptake_times),
                'mean': safe_float(statistics.mean(uptake_times)) if uptake_times else None,
                'median': safe_float(statistics.median(uptake_times)) if uptake_times else None,
                'std_dev': safe_float(statistics.stdev(uptake_times)) if len(uptake_times) > 1 else None,
                'min': safe_float(min(uptake_times)) if uptake_times else None,
                'max': safe_float(max(uptake_times)) if uptake_times else None,
                'ideal': IDEAL_UPTAKE_TIME_MINUTES,
                'within_ideal_range': len([t for t in uptake_times if 45 <= t <= 75]) if uptake_times else 0
            },
            'dose_per_kg': {
                'count': len(doses_per_kg),
                'mean': safe_float(statistics.mean(doses_per_kg)) if doses_per_kg else None,
                'median': safe_float(statistics.median(doses_per_kg)) if doses_per_kg else None,
                'std_dev': safe_float(statistics.stdev(doses_per_kg)) if len(doses_per_kg) > 1 else None,
                'min': safe_float(min(doses_per_kg)) if doses_per_kg else None,
                'max': safe_float(max(doses_per_kg)) if doses_per_kg else None,
                'ideal': IDEAL_DOSE_PER_KG_MBQ,
                'within_ideal_range': len([d for d in doses_per_kg if 2.5 <= d <= 3.5]) if doses_per_kg else 0
            },
            'radiopharmaceuticals': dict(sorted(radiopharmaceuticals.items(), key=lambda x: x[1], reverse=True)[:10]),
            'radiopharmaceutical_total_series': radiopharm_total_series,
            'manufacturers': dict(sorted(manufacturers.items(), key=lambda x: x[1], reverse=True)[:10]),
            'scan_duration': safe_stats(scan_durations),
            'redo_rate': {
                "total": redo_total,
                "repeats": redo_with_repeats
            },
            'missingness': {
                "weight": missing_weight,
                "height": missing_height,
                "birth_date": missing_birth_date,
                "series_weight": missing_series_weight,
                "series_injection_time": missing_series_injection,
                "series_acquisition_time": missing_series_acquisition
            },
            'ctp_flagged': ctp_flagged,
            'sex_counts': sex_counts,
            'age_buckets': age_buckets,
            'study_dates': dict(sorted(study_dates.items(), reverse=True)[:10]),
            'study_hours': dict(sorted(study_hours.items())),
            'modality_summary': dict(sorted(modality_summary.items(), key=lambda x: x[1]["count"], reverse=True)),
            'radiopharm_summary': dict(sorted(radiopharm_summary.items(), key=lambda x: x[1]["count"], reverse=True)),
            'ct_summary': dict(sorted(ct_summary.items(), key=lambda x: x[1]["count"], reverse=True))
        }

        # Track CSA series hash for QA scoring (used in index filter)
        csa_series_counts = {}
        for row in representative_series_rows:
            csa_series = row.get("csa_series_header_hash")
            if csa_series:
                csa_series_counts[csa_series] = csa_series_counts.get(csa_series, 0) + 1
        majority_csa = max(csa_series_counts, key=csa_series_counts.get) if csa_series_counts else None

        # QA: Metadata completeness (study-level, representative studies only)
        representative_study_uids = {
            row.get("study_instance_uid")
            for row in representative_series_rows
            if row.get("study_instance_uid")
        }
        study_total = len(representative_study_uids)
        completeness_counts = {
            "weight": 0,
            "dose": 0,
            "injection_time": 0,
            "acquisition_time": 0,
            "radiopharmaceutical": 0,
            "patient_sex": 0,
            "patient_age": 0
        }
        radiopharm_study_total = 0
        summary_by_uid = {study["study_instance_uid"]: study for study in study_summary if study.get("study_instance_uid")}
        study_flags = {}
        for study_uid in representative_study_uids:
            study = summary_by_uid.get(study_uid, {})
            study_flags[study_uid] = {
                "weight": parse_db_float(study.get("patient_weight")) is not None,
                "patient_sex": bool(study.get("patient_sex")),
                "patient_age": bool(study.get("patient_age") or study.get("patient_birth_date")),
                "dose": False,
                "injection_time": False,
                "acquisition_time": False,
                "radiopharmaceutical": False
            }
            modalities = study_modalities.get(study_uid, set())
            if any(is_radiopharm_modality(m or "") for m in modalities):
                radiopharm_study_total += 1

        for row in representative_series_rows:
            study_uid = row.get("study_instance_uid")
            if not study_uid or study_uid not in study_flags:
                continue
            modality = row.get("modality") or ""
            if is_radiopharm_modality(modality):
                if parse_db_float(row.get("injected_activity")) is not None:
                    study_flags[study_uid]["dose"] = True
                if row.get("injection_time"):
                    study_flags[study_uid]["injection_time"] = True
            if row.get("acquisition_time"):
                study_flags[study_uid]["acquisition_time"] = True
            if is_radiopharm_modality(modality) and has_radiopharm(row):
                study_flags[study_uid]["radiopharmaceutical"] = True

        for flags in study_flags.values():
            for key in completeness_counts:
                if flags.get(key):
                    completeness_counts[key] += 1

        # QA: Timing integrity
        timing_counts = {
            "negative": 0,
            "too_long": 0,
            "parse_fail": 0,
            "missing": 0,
            "study_time_conflict": 0
        }
        for row in representative_series_rows:
            _, status = compute_delay_status(row)
            if status in timing_counts:
                timing_counts[status] += 1
            if has_time_conflict(row):
                timing_counts["study_time_conflict"] += 1

        # QA: Dose plausibility
        dose_values = []
        missing_activity_has_weight = 0
        missing_weight_has_activity = 0
        possible_unit_mismatch = 0
        radiopharm_dose_total = 0
        for row in representative_series_rows:
            modality = row.get("modality") or ""
            if not is_radiopharm_modality(modality):
                continue
            radiopharm_dose_total += 1
            dose_per_kg, activity_mbq = compute_dose_from_row(row)
            injected_activity = parse_db_float(row.get("injected_activity"))
            patient_weight = get_patient_weight(row)
            if patient_weight and injected_activity is None:
                missing_activity_has_weight += 1
            if injected_activity is not None and not patient_weight:
                missing_weight_has_activity += 1
            if dose_per_kg is not None:
                dose_values.append(dose_per_kg)
                if dose_per_kg < 0.1 or dose_per_kg > 50:
                    possible_unit_mismatch += 1
        dose_mean = statistics.mean(dose_values) if dose_values else None
        dose_std = statistics.stdev(dose_values) if len(dose_values) > 1 else None
        dose_outliers = 0
        if dose_mean is not None and dose_std:
            for value in dose_values:
                if abs(value - dose_mean) > 3 * dose_std:
                    dose_outliers += 1

        # QA: Scanner landscape
        scanner_groups = {}
        for row in representative_series_rows:
            key = (
                row.get("manufacturer") or "Unknown",
                row.get("manufacturer_model_name") or "Unknown",
                row.get("software_version") or "Unknown"
            )
            entry = scanner_groups.setdefault(key, {
                "count": 0,
                "csa_hashes": set()
            })
            entry["count"] += 1
            if row.get("csa_series_header_hash"):
                entry["csa_hashes"].add(row["csa_series_header_hash"])
        scanner_landscape = [
            {
                "manufacturer": key[0],
                "model": key[1],
                "software": key[2],
                "count": data["count"],
                "unique_csa": len(data["csa_hashes"])
            }
            for key, data in scanner_groups.items()
        ]
        scanner_landscape.sort(key=lambda x: x["count"], reverse=True)

        # QA: Protocol fingerprint vs radiopharmaceutical
        protocol_radiopharm = []
        radiopharm_fps = {}
        for row in representative_series_rows:
            radiopharm = row.get("radiopharmaceutical") or "Unknown"
            fp = row.get("csa_series_header_hash")
            if not fp:
                continue
            entry = radiopharm_fps.setdefault(radiopharm, {})
            entry[fp] = entry.get(fp, 0) + 1
        for radiopharm, fp_counts in radiopharm_fps.items():
            sorted_fps = sorted(fp_counts.items(), key=lambda x: x[1], reverse=True)
            top_fp, top_count = sorted_fps[0]
            protocol_radiopharm.append({
                "radiopharmaceutical": radiopharm,
                "unique_fps": len(fp_counts),
                "top_fp": top_fp,
                "top_count": top_count
            })
        protocol_radiopharm.sort(key=lambda x: x["unique_fps"], reverse=True)

        # QA: Derived object provenance
        derived_counts = {
            "seg": 0,
            "rtstruct": 0,
            "highdicom": 0,
            "qiicr": 0
        }
        for row in representative_series_rows:
            modality = (row.get("modality") or "").upper()
            manufacturer = (row.get("manufacturer") or "").lower()
            if modality == "SEG":
                derived_counts["seg"] += 1
            if modality == "RTSTRUCT":
                derived_counts["rtstruct"] += 1
            if manufacturer == "highdicom":
                derived_counts["highdicom"] += 1
            if manufacturer == "qiicr":
                derived_counts["qiicr"] += 1

        ctp_label_counts = []
        try:
            representative_series_uids = [
                row.get("series_instance_uid")
                for row in representative_series_rows
                if row.get("series_instance_uid")
            ]
            if representative_series_uids:
                conn = get_db_connection(db_path)
                counts = {}
                chunk_size = 900
                for i in range(0, len(representative_series_uids), chunk_size):
                    chunk = representative_series_uids[i:i + chunk_size]
                    placeholders = ",".join(["?"] * len(chunk))
                    cursor = conn.execute(f"""
                        SELECT value_text, COUNT(*) as count
                        FROM private_tag
                        WHERE creator = 'CTP'
                          AND group_hex = '0013'
                          AND element_hex = '1010'
                          AND value_text IS NOT NULL
                          AND value_text != ''
                          AND series_instance_uid IN ({placeholders})
                        GROUP BY value_text
                    """, chunk)
                    for row in cursor.fetchall():
                        value_text = row["value_text"]
                        counts[value_text] = counts.get(value_text, 0) + int(row["count"])
                conn.close()
                ctp_label_counts = [
                    {"value_text": value_text, "count": count}
                    for value_text, count in sorted(counts.items(), key=lambda x: x[1], reverse=True)[:10]
                ]
        except Exception:
            ctp_label_counts = []

        # QA: Duplicate detection (representative series only)
        sop_counts = {}
        for row in representative_series_rows:
            sop_uid = row.get("sop_instance_uid")
            if sop_uid:
                sop_counts[sop_uid] = sop_counts.get(sop_uid, 0) + 1
        duplicate_sop_count = sum(1 for count in sop_counts.values() if count > 1)

        series_signature_counts = {}
        for row in representative_series_rows:
            signature = (
                row.get("study_instance_uid"),
                row.get("modality"),
                row.get("series_description"),
                row.get("acquisition_date"),
                row.get("acquisition_time"),
                row.get("number_of_slices")
            )
            series_signature_counts[signature] = series_signature_counts.get(signature, 0) + 1
        duplicate_series_signatures = sum(1 for count in series_signature_counts.values() if count > 1)

        # QA: Study composition
        studies_missing_ct = sum(1 for mods in study_modalities.values() if "PT" in mods and "CT" not in mods)
        studies_missing_pt = sum(1 for mods in study_modalities.values() if "CT" in mods and "PT" not in mods)
        studies_high_series = sum(1 for count in study_series_counts.values() if count > 20)

        # QA: Score distribution
        qa_scores = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        for row in representative_series_rows:
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
            qa_scores[score] += 1

        completeness_stats = {
            "total": study_total,
            "counts": completeness_counts,
            "totals": {
                "weight": study_total,
                "dose": radiopharm_study_total,
                "injection_time": radiopharm_study_total,
                "acquisition_time": study_total,
                "radiopharmaceutical": radiopharm_study_total,
                "patient_sex": study_total,
                "patient_age": study_total
            }
        }
        timing_stats = timing_counts
        dose_stats = {
            "outliers": dose_outliers,
            "unit_mismatch": possible_unit_mismatch,
            "missing_activity_has_weight": missing_activity_has_weight,
            "missing_weight_has_activity": missing_weight_has_activity,
            "total": radiopharm_dose_total,
            "mean": dose_mean,
            "std_dev": dose_std
        }
        derived_stats = {
            "seg": derived_counts["seg"],
            "rtstruct": derived_counts["rtstruct"],
            "highdicom": derived_counts["highdicom"],
            "qiicr": derived_counts["qiicr"],
            "ctp_labels": ctp_label_counts
        }
        duplicate_stats = {
            "duplicate_sop": duplicate_sop_count,
            "duplicate_series_signatures": duplicate_series_signatures
        }
        study_comp_stats = {
            "missing_ct": studies_missing_ct,
            "missing_pt": studies_missing_pt,
            "high_series": studies_high_series
        }
        
        # Create histogram data for charts
        def create_histogram(data, bins=20, min_val=None, max_val=None, precision=1, bin_width=None, max_bins=60):
            if not data:
                return {'labels': [], 'values': []}
            
            if min_val is None:
                min_val = float(min(data))
            if max_val is None:
                max_val = float(max(data))
            
            # Ensure we have valid range
            if max_val <= min_val:
                max_val = min_val + 1

            if bin_width:
                bins = int(math.ceil((max_val - min_val) / bin_width))
                bins = max(1, min(bins, max_bins))
            bin_width = (max_val - min_val) / bins
            histogram = [0] * bins
            labels = []
            
            for i in range(bins):
                labels.append(f"{min_val + i * bin_width:.{precision}f}")
            
            for value in data:
                val = float(value)
                if min_val <= val <= max_val:
                    bin_index = min(int((val - min_val) / bin_width), bins - 1)
                    histogram[bin_index] += 1
            
            return {'labels': labels, 'values': histogram}
        
        max_uptake = float(max(uptake_times)) if uptake_times else 180.0
        uptake_histogram = create_histogram(
            uptake_times,
            min_val=0,
            max_val=max_uptake,
            precision=1,
            bin_width=5,
            max_bins=60
        )
        max_dose = float(max(doses_per_kg)) if doses_per_kg else 10.0
        dose_histogram = create_histogram(
            doses_per_kg,
            min_val=0,
            max_val=max_dose,
            precision=2,
            bin_width=0.1,
            max_bins=80
        )
        
        # Ensure all histogram data is JSON serializable (convert to lists explicitly)
        uptake_histogram_clean = {
            'labels': list(uptake_histogram['labels']),
            'values': [int(v) for v in uptake_histogram['values']]
        }
        dose_histogram_clean = {
            'labels': list(dose_histogram['labels']),
            'values': [int(v) for v in dose_histogram['values']]
        }
        return render_template('dashboard.html', 
                             stats=stats,
                             uptake_histogram=uptake_histogram_clean,
                             dose_histogram=dose_histogram_clean,
                             completeness_stats=completeness_stats,
                             timing_stats=timing_stats,
                             dose_stats=dose_stats,
                             scanner_landscape=scanner_landscape,
                             protocol_radiopharm=protocol_radiopharm,
                             derived_stats=derived_stats,
                             duplicate_stats=duplicate_stats,
                             study_comp_stats=study_comp_stats,
                             qa_scores=qa_scores,
                             db_name=db_name,
                             databanks=databanks,
                             t=translations,
                             lang=get_language())
    except Exception as e:
        return f"Error: {str(e)}", 500


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


def format_date(date_str):
    """Format DICOM date (YYYYMMDD) to DD/MM/YYYY format"""
    if not date_str or len(date_str) < 8:
        return date_str
    try:
        # DICOM format: YYYYMMDD
        year = date_str[:4]
        month = date_str[4:6]
        day = date_str[6:8]
        return f"{day}/{month}/{year}"
    except:
        return date_str


def format_time(time_str):
    """Format DICOM time (HHMMSS.frac) to human-readable format (HH:MM:SS)"""
    if not time_str:
        return time_str
    try:
        # Handle string or numeric input
        time_str = str(time_str).strip()
        
        # DICOM TM format: HHMMSS[.frac] - at least 6 digits
        if len(time_str) >= 6:
            hours = time_str[:2]
            minutes = time_str[2:4]
            seconds = time_str[4:6]
            
            # Handle fractional seconds if present
            if '.' in time_str and len(time_str) > 6:
                # Extract fractional part but don't display (optional)
                frac_part = time_str.split('.', 1)[1]
                if frac_part:
                    # Show seconds with 1 decimal place if fractional part exists
                    return f"{hours}:{minutes}:{seconds}.{frac_part[:1]}"
            
            return f"{hours}:{minutes}:{seconds}"
        return time_str
    except Exception:
        return time_str


def format_private_timestamp(value_text: Optional[object]) -> Optional[str]:
    """Best-effort formatting for private-tag timestamps."""
    if value_text is None:
        return None
    text = str(value_text).strip()
    if not text:
        return None
    try:
        if re.fullmatch(r"\d{8}", text):
            return format_date(text)
        if re.fullmatch(r"\d{14}(\.\d+)?", text):
            date_part = text[:8]
            time_part = text[8:]
            return f"{format_date(date_part)} {format_time(time_part)}"
        if re.fullmatch(r"\d{6}(\.\d+)?", text):
            return format_time(text)
        if re.fullmatch(r"\d{2}:\d{2}:\d{2}(\.\d+)?", text):
            parts = text.split(".", 1)
            base = parts[0]
            if len(parts) > 1 and parts[1]:
                return f"{base}.{parts[1][:1]}"
            return base
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(\.\d+)?", text):
            from datetime import datetime
            cleaned = text.replace("T", " ")
            fmt = "%Y-%m-%d %H:%M:%S.%f" if "." in cleaned else "%Y-%m-%d %H:%M:%S"
            return datetime.strptime(cleaned, fmt).strftime("%Y-%m-%d %H:%M:%S")
        if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4} \d{1,2}:\d{2}:\d{2}(\s*[AP]M)?", text):
            from datetime import datetime
            for fmt in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M:%S"):
                try:
                    return datetime.strptime(text, fmt).strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue
    except Exception:
        return text
    return text


def parse_pet_dose_report(xml_text: str) -> Optional[List[dict]]:
    if not xml_text:
        return None
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return None
    names = [n.text for n in root.findall(".//m_StatisticsNameVector") if n.text]
    values1 = [v.text for v in root.findall(".//m_StatisticsValueVector1")]
    values2 = [v.text for v in root.findall(".//m_StatisticsValueVector2")]
    entries = []
    for idx, name in enumerate(names):
        val1 = values1[idx] if idx < len(values1) else None
        val2 = values2[idx] if idx < len(values2) else None
        if val1 is None and val2 is None:
            continue
        entries.append({
            "name": name,
            "value": val1,
            "alt_value": val2
        })
    return entries or None


def parse_time_to_24hour(time_str):
    """Parse time string and convert to 24-hour format, handling 12-hour format errors
    
    Returns: (hour, minute, second) tuple in 24-hour format, or None if parsing fails
    """
    if not time_str:
        return None
    try:
        time_str = str(time_str).strip()
        
        # Remove fractional seconds for parsing
        if '.' in time_str:
            time_str = time_str.split('.')[0]
        
        if len(time_str) >= 6:
            hours = int(time_str[:2])
            minutes = int(time_str[2:4])
            seconds = int(time_str[4:6]) if len(time_str) >= 6 else 0
            
            return (hours, minutes, seconds)
    except Exception:
        return None
    return None


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
        from datetime import datetime
        year = int(date_str[:4])
        month = int(date_str[4:6])
        day = int(date_str[6:8])
        dt = datetime(year, month, day)
        return (dt - datetime(1970, 1, 1)).days
    except Exception:
        return None


def calculate_injection_delay(injection_date, injection_time, acquisition_date, acquisition_time, injection_date_missing=False, study_time=None):
    """Calculate delay between injection and acquisition in minutes.
    
    This version ships raw DICOM times without applying any time correction heuristics.
    """
    if not injection_date or not injection_time or not acquisition_date or not acquisition_time:
        return None, None

    try:
        from datetime import datetime

        inj_date_str = str(injection_date).strip()
        acq_date_str = str(acquisition_date).strip()

        if len(inj_date_str) < 8 or len(acq_date_str) < 8:
            return None, None

        inj_time_parsed = parse_time_to_24hour(injection_time)
        acq_time_parsed = parse_time_to_24hour(acquisition_time)

        if not inj_time_parsed or not acq_time_parsed:
            return None, None

        inj_year = int(inj_date_str[:4])
        inj_month = int(inj_date_str[4:6])
        inj_day = int(inj_date_str[6:8])
        inj_hour, inj_min, inj_sec = inj_time_parsed

        acq_year = int(acq_date_str[:4])
        acq_month = int(acq_date_str[4:6])
        acq_day = int(acq_date_str[6:8])
        acq_hour, acq_min, acq_sec = acq_time_parsed

        injection_dt = datetime(inj_year, inj_month, inj_day, inj_hour, inj_min, inj_sec)
        acquisition_dt = datetime(acq_year, acq_month, acq_day, acq_hour, acq_min, acq_sec)

        delay = acquisition_dt - injection_dt
        delay_minutes = delay.total_seconds() / 60

        if delay_minutes < 0:
            return None, None

        return delay_minutes, None
    except Exception:
        return None, None


def calculate_patient_age(birth_date, study_date):
    """Calculate patient age in years from birth date and study date"""
    if not birth_date or not study_date:
        return None
    
    try:
        from datetime import datetime
        
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
        import math
        # Activity = A0 * e^(-lambda * t)
        # where lambda = ln(2) / half_life
        lambda_decay = math.log(2) / half_life_seconds
        time_seconds = delay_minutes * 60
        remaining_activity = injected_activity * math.exp(-lambda_decay * time_seconds)
        return remaining_activity
    except Exception:
        return None


def format_delay(minutes):
    """Format delay in minutes to human-readable format"""
    if minutes is None:
        return None
    
    try:
        if minutes < 60:
            return f"{minutes:.1f} minutes"
        elif minutes < 1440:  # Less than 24 hours
            hours = minutes / 60
            return f"{hours:.1f} hours ({minutes:.0f} min)"
        else:
            days = minutes / 1440
            return f"{days:.1f} days ({minutes:.0f} min)"
    except Exception:
        return None


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    print(f"Starting DICOM Metadata Browser on http://127.0.0.1:{port}")
    print(f"Using database: {DEFAULT_DB}")
    app.run(debug=False, host='127.0.0.1', port=port)

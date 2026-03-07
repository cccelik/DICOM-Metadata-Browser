#!/usr/bin/env python3
"""
Export and formatting helpers for the web UI.
"""

import csv
from datetime import datetime
import math
import re
import secrets
import string
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Set, Tuple

from qa_utils import (
    RADIOPHARM_MODALITIES,
    calculate_raw_injection_delay_minutes,
    get_patient_weight,
    parse_db_float,
)


def build_export_sections(translations: dict, export_sections: List[dict]) -> tuple[List[dict], dict]:
    sections = []
    label_map = {}
    for section in export_sections:
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


def build_anonymize_fields(translations: dict, anonymize_fields: List[dict]) -> List[dict]:
    fields = []
    for field in anonymize_fields:
        field_name = field["name"]
        label_key = field.get("label_key", field_name)
        label = translations.get(label_key, label_key.replace("_", " ").title())
        fields.append({
            "name": field_name,
            "label": label,
            "default": field.get("default", False),
        })
    return fields


def resolve_export_fields(requested_fields: List[str], field_order: List[str], default_fields: List[str]) -> List[str]:
    selected_fields = [name for name in field_order if name in requested_fields]
    if not selected_fields:
        return list(default_fields)
    return selected_fields


def resolve_csv_anonymize_fields(
    requested_fields: List[str],
    enabled: bool,
    field_order: List[str],
    default_fields: List[str],
) -> List[str]:
    if not enabled:
        return []
    requested_set = {name for name in requested_fields if name in field_order}
    selected_set = set(default_fields) | requested_set
    return [name for name in field_order if name in selected_set]


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
    return str(modality).strip().upper() in RADIOPHARM_MODALITIES


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


def format_date(date_str):
    if not date_str or len(date_str) < 8:
        return date_str
    try:
        year = date_str[:4]
        month = date_str[4:6]
        day = date_str[6:8]
        return f"{day}/{month}/{year}"
    except (TypeError, ValueError, IndexError):
        return date_str


def format_time(time_str):
    if not time_str:
        return time_str
    try:
        time_str = str(time_str).strip()
        if len(time_str) >= 6:
            hours = time_str[:2]
            minutes = time_str[2:4]
            seconds = time_str[4:6]
            if '.' in time_str and len(time_str) > 6:
                frac_part = time_str.split('.', 1)[1]
                if frac_part:
                    return f"{hours}:{minutes}:{seconds}.{frac_part[:1]}"
            return f"{hours}:{minutes}:{seconds}"
        return time_str
    except Exception:
        return time_str


def format_private_timestamp(value_text: Optional[object]) -> Optional[str]:
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
            cleaned = text.replace("T", " ")
            fmt = "%Y-%m-%d %H:%M:%S.%f" if "." in cleaned else "%Y-%m-%d %H:%M:%S"
            return datetime.strptime(cleaned, fmt).strftime("%Y-%m-%d %H:%M:%S")
        if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4} \d{1,2}:\d{2}:\d{2}(\s*[AP]M)?", text):
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
    except ET.ParseError:
        return None
    names = [elem.text for elem in root.findall(".//m_StatisticsNameVector") if elem.text]
    values1 = [elem.text for elem in root.findall(".//m_StatisticsValueVector1")]
    values2 = [elem.text for elem in root.findall(".//m_StatisticsValueVector2")]
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


def calculate_injection_delay(injection_date, injection_time, acquisition_date, acquisition_time, injection_date_missing=False, study_time=None):
    delay_minutes = calculate_raw_injection_delay_minutes(
        injection_date,
        injection_time,
        acquisition_date,
        acquisition_time,
    )
    if delay_minutes is None or delay_minutes < 0:
        return None, None
    return delay_minutes, None


def format_delay(minutes):
    if minutes is None:
        return None
    try:
        if minutes < 60:
            return f"{minutes:.1f} minutes"
        if minutes < 1440:
            hours = minutes / 60
            return f"{hours:.1f} hours ({minutes:.0f} min)"
        days = minutes / 1440
        return f"{days:.1f} days ({minutes:.0f} min)"
    except Exception:
        return None


def format_export_value(
    field_name: str,
    row_dict: dict,
    *,
    export_date_fields: Set[str],
    export_time_fields: Set[str],
    export_numeric_formats: Dict[str, Tuple[Optional[str], int]],
) -> str:
    value = row_dict.get(field_name)
    if value is None:
        return ""
    if field_name == "patient_name":
        return format_patient_name(value)
    if field_name in export_date_fields:
        return format_date(str(value))
    if field_name in export_time_fields:
        return format_time(value)
    if field_name == "injected_activity":
        return format_injected_activity(value, row_dict.get("injected_activity_unit"))
    if field_name == "radionuclide_total_dose":
        return format_total_dose(value)
    if field_name == "uptake_delay":
        precomputed_delay = row_dict.get("uptake_delay") or row_dict.get("injection_delay")
        if precomputed_delay:
            return str(precomputed_delay)
        fallback_date = row_dict.get("study_date") or row_dict.get("acquisition_date") or row_dict.get("series_date")
        injection_date = row_dict.get("injection_date") or row_dict.get("modality_injection_date") or fallback_date
        acquisition_date = row_dict.get("acquisition_date") or row_dict.get("modality_acquisition_date") or fallback_date
        injection_time = row_dict.get("injection_time") or row_dict.get("modality_injection_time")
        acquisition_time = row_dict.get("acquisition_time") or row_dict.get("series_time")
        if injection_date and acquisition_date and injection_time and acquisition_time:
            delay_minutes, _ = calculate_injection_delay(
                injection_date, injection_time, acquisition_date, acquisition_time,
                injection_date_missing=(row_dict.get("injection_date") is None),
                study_time=row_dict.get("study_time"),
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
        patient_weight = parse_db_float(row_dict.get("patient_weight") or row_dict.get("study_patient_weight"))
        patient_size = parse_db_float(row_dict.get("patient_size") or row_dict.get("study_patient_size"))
        if patient_weight and patient_size and patient_size > 0:
            return f"{(patient_weight / (patient_size * patient_size)):.1f}"
        return ""
    if field_name in export_numeric_formats:
        unit, decimals = export_numeric_formats[field_name]
        return format_number_with_unit(value, unit, decimals)
    return str(value)


def _generate_anonymized_value(field_name: str, index: int) -> str:
    prefix = re.sub(r"[^A-Za-z0-9]+", "", field_name).upper()[:10] or "FIELD"
    token = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
    return f"{prefix}_{index:04d}_{token}"


def anonymize_export_value(
    field_name: str,
    row_dict: dict,
    anonymize_fields: Set[str],
    anonymize_cache: Dict[Tuple[str, str], str],
    anonymize_counts: Dict[str, int],
    *,
    anonymize_blank_fields: Set[str],
    export_date_fields: Set[str],
    export_time_fields: Set[str],
    export_numeric_formats: Dict[str, Tuple[Optional[str], int]],
) -> str:
    if field_name not in anonymize_fields:
        return format_export_value(
            field_name,
            row_dict,
            export_date_fields=export_date_fields,
            export_time_fields=export_time_fields,
            export_numeric_formats=export_numeric_formats,
        )
    value = row_dict.get(field_name)
    if value is None or str(value).strip() == "":
        return ""
    if field_name in anonymize_blank_fields:
        return ""
    cache_key = (field_name, str(value))
    cached = anonymize_cache.get(cache_key)
    if cached is not None:
        return cached
    anonymize_counts[field_name] = anonymize_counts.get(field_name, 0) + 1
    replacement = _generate_anonymized_value(field_name, anonymize_counts[field_name])
    anonymize_cache[cache_key] = replacement
    return replacement


def resolve_export_query_fields(
    selected_fields: List[str],
    derived_fields: Set[str],
    derived_dependencies: Set[str],
    existing_columns: Optional[Set[str]] = None,
) -> Tuple[List[str], List[str], bool]:
    derived_selected = any(field in derived_fields for field in selected_fields)
    extra_fields = sorted(derived_dependencies) if derived_selected else []
    real_fields = [field for field in selected_fields if field not in derived_fields]
    if existing_columns is not None:
        export_fields = [field for field in selected_fields if field in derived_fields or field in existing_columns]
        real_fields = [field for field in real_fields if field in existing_columns]
        extra_fields = [field for field in extra_fields if field in existing_columns]
    else:
        export_fields = list(selected_fields)
    select_fields = list(dict.fromkeys(real_fields + extra_fields))
    return export_fields, select_fields, derived_selected


def write_csv_export_rows(
    writer: csv.writer,
    rows,
    selected_fields: List[str],
    csv_anonymize_fields: Set[str],
    *,
    export_group_clear_fields: List[str],
    anonymize_blank_fields: Set[str],
    export_date_fields: Set[str],
    export_time_fields: Set[str],
    export_numeric_formats: Dict[str, Tuple[Optional[str], int]],
    study_info: Optional[dict] = None,
    sectioned: bool = False,
    suppress_repeats: bool = False,
) -> None:
    last_group_values = {}
    anonymize_cache: Dict[Tuple[str, str], str] = {}
    anonymize_counts: Dict[str, int] = {}
    study_info = study_info or {}

    if sectioned:
        patient_fields = [f for f in selected_fields if f in export_group_clear_fields]
        if patient_fields:
            base_row = dict(rows[0]) if rows else {}
            base_row["study_patient_weight"] = study_info.get("patient_weight")
            base_row["study_patient_size"] = study_info.get("patient_size")
            base_row["study_date"] = base_row.get("study_date") or study_info.get("study_date")
            base_row["study_time"] = base_row.get("study_time") or study_info.get("study_time")
            patient_row = {
                name: anonymize_export_value(
                    name,
                    base_row,
                    csv_anonymize_fields,
                    anonymize_cache,
                    anonymize_counts,
                    anonymize_blank_fields=anonymize_blank_fields,
                    export_date_fields=export_date_fields,
                    export_time_fields=export_time_fields,
                    export_numeric_formats=export_numeric_formats,
                )
                for name in selected_fields
            }
            writer.writerow([patient_row.get(name, "") for name in selected_fields])
            writer.writerow([])

    for index, row in enumerate(rows):
        row_dict = dict(row)
        row_dict["study_patient_weight"] = study_info.get("patient_weight")
        row_dict["study_patient_size"] = study_info.get("patient_size")
        row_dict["study_date"] = row_dict.get("study_date") or study_info.get("study_date")
        row_dict["study_time"] = row_dict.get("study_time") or study_info.get("study_time")
        formatted_row = {
            name: anonymize_export_value(
                name,
                row_dict,
                csv_anonymize_fields,
                anonymize_cache,
                anonymize_counts,
                anonymize_blank_fields=anonymize_blank_fields,
                export_date_fields=export_date_fields,
                export_time_fields=export_time_fields,
                export_numeric_formats=export_numeric_formats,
            )
            for name in selected_fields
        }
        if sectioned:
            for field_name in export_group_clear_fields:
                if field_name in formatted_row:
                    formatted_row[field_name] = ""
        if suppress_repeats and index > 0:
            for field_name in export_group_clear_fields:
                if field_name in formatted_row and formatted_row[field_name] == last_group_values.get(field_name):
                    formatted_row[field_name] = ""
        if index == 0:
            last_group_values = formatted_row.copy()
        writer.writerow([formatted_row.get(name, "") for name in selected_fields])

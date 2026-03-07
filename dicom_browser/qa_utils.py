#!/usr/bin/env python3
"""
Shared QA and representative-selection helpers.
"""

from datetime import datetime
from typing import Dict, List, Optional, Tuple

RADIOPHARM_MODALITIES = {
    "PT",
    "PET",
    "NM",
    "SPECT",
    "NM/CT",
    "PET/CT",
    "SPECT/CT",
}


def parse_db_float(value: Optional[object]) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_time_to_24hour(time_str: Optional[object]) -> Optional[Tuple[int, int, int]]:
    if not time_str:
        return None
    try:
        text = str(time_str).strip()
        if "." in text:
            text = text.split(".", 1)[0]
        if len(text) >= 6:
            return int(text[:2]), int(text[2:4]), int(text[4:6])
    except (TypeError, ValueError):
        return None
    return None


def calculate_raw_injection_delay_minutes(
    injection_date: Optional[object],
    injection_time: Optional[object],
    acquisition_date: Optional[object],
    acquisition_time: Optional[object],
) -> Optional[float]:
    if not injection_date or not injection_time or not acquisition_date or not acquisition_time:
        return None
    try:
        inj_date_str = str(injection_date).strip()
        acq_date_str = str(acquisition_date).strip()
        if len(inj_date_str) < 8 or len(acq_date_str) < 8:
            return None
        inj_time_parsed = parse_time_to_24hour(injection_time)
        acq_time_parsed = parse_time_to_24hour(acquisition_time)
        if not inj_time_parsed or not acq_time_parsed:
            return None
        injection_dt = datetime(
            int(inj_date_str[:4]), int(inj_date_str[4:6]), int(inj_date_str[6:8]),
            inj_time_parsed[0], inj_time_parsed[1], inj_time_parsed[2]
        )
        acquisition_dt = datetime(
            int(acq_date_str[:4]), int(acq_date_str[4:6]), int(acq_date_str[6:8]),
            acq_time_parsed[0], acq_time_parsed[1], acq_time_parsed[2]
        )
        return (acquisition_dt - injection_dt).total_seconds() / 60
    except (TypeError, ValueError):
        return None


def get_patient_weight(row_dict: dict) -> Optional[float]:
    weight = parse_db_float(row_dict.get("patient_weight"))
    if weight is not None and weight > 0:
        return weight
    weight = parse_db_float(row_dict.get("study_patient_weight"))
    if weight is not None and weight > 0:
        return weight
    size_value = parse_db_float(row_dict.get("patient_size"))
    if size_value is not None and 10 < size_value <= 500:
        return size_value
    return None


def compute_delay_minutes(row_dict: dict) -> Optional[float]:
    injection_time = row_dict.get("injection_time")
    acquisition_time = row_dict.get("acquisition_time")
    injection_date = row_dict.get("injection_date") or row_dict.get("study_date")
    acquisition_date = row_dict.get("acquisition_date") or row_dict.get("study_date")
    delay_minutes = calculate_raw_injection_delay_minutes(
        injection_date,
        injection_time,
        acquisition_date,
        acquisition_time,
    )
    if delay_minutes and delay_minutes > 0:
        return delay_minutes
    return None


def compute_dose_per_kg(row_dict: dict) -> Optional[float]:
    patient_weight = get_patient_weight(row_dict)
    injected_activity = parse_db_float(row_dict.get("injected_activity"))
    if patient_weight is None or patient_weight <= 0 or injected_activity is None:
        return None
    activity_mbq = injected_activity / 1e6 if injected_activity > 1e6 else injected_activity
    dose_per_kg = activity_mbq / patient_weight
    if 0 < dose_per_kg < 100:
        return dose_per_kg
    return None


def compute_dose_from_row(row_dict: dict) -> Tuple[Optional[float], Optional[float]]:
    patient_weight = get_patient_weight(row_dict)
    injected_activity = parse_db_float(row_dict.get("injected_activity"))
    if not patient_weight or patient_weight <= 0 or injected_activity is None:
        return None, None
    activity_mbq = injected_activity / 1e6 if injected_activity > 1e6 else injected_activity
    return activity_mbq / patient_weight, activity_mbq


def select_study_representatives(rows: List[dict]) -> Dict[str, dict]:
    representatives: Dict[str, dict] = {}
    for row in rows:
        row_dict = dict(row)
        study_uid = row_dict.get("study_instance_uid")
        if not study_uid:
            continue
        delay_minutes = compute_delay_minutes(row_dict)
        dose_per_kg = compute_dose_per_kg(row_dict)
        score = 0
        if dose_per_kg is not None:
            score += 3
        if delay_minutes is not None:
            score += 2
        if (row_dict.get("modality") or "").upper() in RADIOPHARM_MODALITIES:
            score += 1
        current = representatives.get(study_uid)
        if current is None or score > current["score"]:
            representatives[study_uid] = {
                "score": score,
                "row": row_dict,
                "delay_minutes": delay_minutes,
                "dose_per_kg": dose_per_kg,
            }
    return representatives

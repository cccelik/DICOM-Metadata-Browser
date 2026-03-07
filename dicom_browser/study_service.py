#!/usr/bin/env python3
"""
Study detail payload assembly.
"""

import os
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .export_utils import (
    calculate_injection_delay,
    format_date,
    format_delay,
    format_patient_name,
    format_private_timestamp,
    format_time,
    parse_pet_dose_report,
)


def resolve_display_path(scan_root: Optional[str], file_path: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if not file_path:
        return None, None
    try:
        path = Path(file_path)
        if path.is_absolute():
            return str(path), None
    except Exception:
        return None, None
    if scan_root and scan_root.startswith("zip:"):
        zip_name = scan_root.split("zip:", 1)[1]
        display_path = str(Path(zip_name) / file_path)
        label = f"Extracted from uploaded zip file: {zip_name}"
        return display_path, label
    if scan_root:
        return str(Path(scan_root) / file_path), None
    return None, None


def _load_private_tag_items(
    conn: sqlite3.Connection,
    series_uids: List[str],
    classification: str,
) -> Dict[str, List[dict]]:
    if not series_uids:
        return {}
    placeholders = ",".join(["?"] * len(series_uids))
    cursor = conn.execute(
        f"""
        SELECT series_instance_uid, creator, group_hex, element_hex, value_text, value_num, value_hex
        FROM private_tag
        WHERE series_instance_uid IN ({placeholders})
          AND classification = ?
        ORDER BY series_instance_uid, creator, group_hex, element_hex
        """,
        [*series_uids, classification],
    )
    grouped: Dict[str, List[dict]] = {}
    for row in cursor.fetchall():
        item = dict(row)
        raw_value = item.get("value_text")
        if raw_value is None and item.get("value_num") is not None:
            raw_value = str(item["value_num"])
        formatted = format_private_timestamp(raw_value) if raw_value else None
        item["display_value"] = formatted or raw_value or item.get("value_hex")
        grouped.setdefault(item["series_instance_uid"], []).append(item)
    return grouped


def build_study_detail_payload(
    conn: sqlite3.Connection,
    study_uid: str,
    *,
    calculate_activity_at_scan,
) -> Optional[dict]:
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
    study_row = cursor.fetchone()
    if not study_row:
        return None
    study_info = dict(study_row)

    cursor = conn.execute("""
        SELECT
            series_instance_uid,
            series_number,
            series_description,
            series_date,
            series_time,
            modality,
            scan_root,
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
        FROM dicom_metadata
        WHERE study_instance_uid = ?
        ORDER BY series_number ASC, series_time ASC, series_instance_uid ASC
    """, (study_uid,))
    series = [dict(row) for row in cursor.fetchall()]

    study_paths = set()
    study_labels = set()
    for item in series:
        abs_path, path_label = resolve_display_path(item.get("scan_root"), item.get("file_path"))
        if abs_path:
            item["absolute_file_path"] = abs_path
            study_paths.add(abs_path)
        if path_label:
            item["absolute_path_label"] = path_label
            study_labels.add(path_label)

    if study_paths:
        try:
            common_root = os.path.commonpath(sorted(study_paths))
        except ValueError:
            common_root = None
        study_info["study_absolute_paths"] = [common_root] if common_root else sorted(study_paths)
    else:
        study_info["study_absolute_paths"] = []
    study_info["study_absolute_path_labels"] = sorted(study_labels)

    export_modalities = sorted({item.get("modality") for item in series if item.get("modality")})
    series_uids = [item.get("series_instance_uid") for item in series if item.get("series_instance_uid")]
    private_creators: Dict[str, dict] = {}
    pipeline_tags: Dict[str, List[dict]] = {}
    rt_tags: Dict[str, List[dict]] = {}
    pet_dose_reports: Dict[str, List[dict]] = {}

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

        pipeline_tags = _load_private_tag_items(conn, series_uids, "pipeline_provenance")
        rt_tags = _load_private_tag_items(conn, series_uids, "rt_provenance")

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
        for row in cursor.fetchall():
            entries = parse_pet_dose_report(row["value_text"])
            if entries:
                pet_dose_reports[row["series_instance_uid"]] = entries

    if study_info.get("study_date"):
        study_info["study_date_formatted"] = format_date(study_info["study_date"])
    if study_info.get("study_time"):
        study_info["study_time_formatted"] = format_time(study_info["study_time"])
    if study_info.get("patient_birth_date"):
        study_info["patient_birth_date_formatted"] = format_date(study_info["patient_birth_date"])
    study_info["patient_name_display"] = format_patient_name(study_info.get("patient_name")) or None

    if study_info.get("patient_weight") and study_info.get("patient_size"):
        height_m = study_info["patient_size"]
        if height_m and height_m > 0:
            study_info["bmi"] = study_info["patient_weight"] / (height_m * height_m)
            study_info["height_cm"] = height_m * 100

    for item in series:
        creator_counts = private_creators.get(item.get("series_instance_uid"), {})
        item["private_creators"] = dict(sorted(creator_counts.items(), key=lambda x: x[1], reverse=True))
        item["pipeline_provenance"] = pipeline_tags.get(item.get("series_instance_uid"), [])
        item["rt_provenance"] = rt_tags.get(item.get("series_instance_uid"), [])
        item["pet_dose_report"] = pet_dose_reports.get(item.get("series_instance_uid"))

        if item.get("series_date"):
            item["series_date_formatted"] = format_date(item["series_date"])
        if item.get("series_time"):
            item["series_time_formatted"] = format_time(item["series_time"])
        if item.get("acquisition_date"):
            item["acquisition_date_formatted"] = format_date(item["acquisition_date"])
        if item.get("acquisition_time"):
            item["acquisition_time_formatted"] = format_time(item["acquisition_time"])
            if study_info.get("study_time"):
                try:
                    study_hours = int(str(study_info["study_time"])[:2])
                    acq_hours = int(str(item["acquisition_time"])[:2])
                    if study_hours >= 22 and acq_hours <= 6:
                        item["acquisition_likely_next_day"] = True
                except (TypeError, ValueError):
                    pass
        if item.get("injection_date"):
            item["injection_date_formatted"] = format_date(item["injection_date"])
        if item.get("injection_time"):
            item["injection_time_formatted"] = format_time(item["injection_time"])

        injection_date_to_use = item.get("injection_date") or study_info.get("study_date")
        acquisition_date_to_use = item.get("acquisition_date") or study_info.get("study_date")
        if (
            injection_date_to_use and item.get("injection_time")
            and acquisition_date_to_use and item.get("acquisition_time")
        ):
            delay_minutes, _ = calculate_injection_delay(
                injection_date_to_use,
                item["injection_time"],
                acquisition_date_to_use,
                item["acquisition_time"],
                injection_date_missing=(item.get("injection_date") is None),
                study_time=study_info.get("study_time"),
            )
            if delay_minutes:
                item["injection_delay"] = format_delay(delay_minutes)
                item["injection_delay_minutes"] = delay_minutes

        if item.get("injected_activity") and study_info.get("patient_weight"):
            item["activity_per_kg"] = item["injected_activity"] / study_info["patient_weight"]

        if item.get("injected_activity") and item.get("half_life") and item.get("injection_delay_minutes"):
            injected_activity_bq = item["injected_activity"]
            if injected_activity_bq < 1e6:
                injected_activity_bq = injected_activity_bq * 1e6
            remaining_activity = calculate_activity_at_scan(
                injected_activity_bq,
                item["half_life"],
                item["injection_delay_minutes"],
            )
            if remaining_activity:
                item["activity_at_scan"] = remaining_activity
                if injected_activity_bq > 0:
                    item["decay_percent"] = (1 - remaining_activity / injected_activity_bq) * 100

    return {
        "study_info": study_info,
        "series": series,
        "export_modalities": export_modalities,
    }

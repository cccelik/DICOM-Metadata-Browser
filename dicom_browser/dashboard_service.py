#!/usr/bin/env python3
"""
Dashboard aggregation helpers.
"""

import math
import sqlite3
import statistics
from typing import Dict, List, Optional

from .export_utils import is_radiopharm_modality
from .qa_utils import compute_dose_from_row, get_patient_weight, parse_db_float
from .store_metadata import init_database

IDEAL_UPTAKE_TIME_MINUTES = 60
IDEAL_DOSE_PER_KG_MBQ = 3.0


def build_dashboard_payload(
    *,
    study_summary: List[dict],
    study_modalities: Dict[str, set],
    representative_series_rows: List[dict],
    db_path: str,
    parse_time_to_24hour,
    calculate_injection_delay,
    compute_delay_status,
    has_time_conflict,
    has_radiopharm,
) -> dict:
    uptake_times = []
    doses_per_kg = []
    scan_durations = []
    radiopharmaceuticals = {}
    manufacturers = {}
    radiopharm_total_series = 0

    modality_stats = {}
    radiopharm_stats = {}
    ct_dose_by_modality = {}

    for row_dict in representative_series_rows:
        modality = row_dict.get('modality') or 'Unknown'
        radiopharm = row_dict.get('radiopharmaceutical') or 'Unknown'

        modality_bucket = modality_stats.setdefault(modality, {
            "count": 0, "uptake_times": [], "doses_per_kg": [],
            "missing_weight": 0, "missing_injection_time": 0, "missing_acquisition_time": 0,
        })
        modality_bucket["count"] += 1

        if is_radiopharm_modality(modality):
            radiopharm_total_series += 1
            radiopharm_bucket = radiopharm_stats.setdefault(radiopharm, {
                "count": 0, "uptake_times": [], "doses_per_kg": [],
                "missing_weight": 0, "missing_injection_time": 0, "missing_acquisition_time": 0,
            })
            radiopharm_bucket["count"] += 1
        else:
            radiopharm_bucket = None

        if (row_dict.get('injection_date') or row_dict.get('study_date')) and row_dict.get('injection_time') and \
           (row_dict.get('acquisition_date') or row_dict.get('study_date')) and row_dict.get('acquisition_time'):
            injection_date = row_dict.get('injection_date') or row_dict.get('study_date')
            acquisition_date = row_dict.get('acquisition_date') or row_dict.get('study_date')
            delay_minutes, _ = calculate_injection_delay(
                injection_date,
                row_dict['injection_time'],
                acquisition_date,
                row_dict['acquisition_time'],
                injection_date_missing=(row_dict.get('injection_date') is None),
            )
            if delay_minutes:
                uptake_times.append(delay_minutes)
                modality_bucket["uptake_times"].append(delay_minutes)
                if radiopharm_bucket is not None:
                    radiopharm_bucket["uptake_times"].append(delay_minutes)

        if not (row_dict.get('acquisition_time') and (row_dict.get('acquisition_date') or row_dict.get('study_date'))):
            modality_bucket["missing_acquisition_time"] += 1
            if radiopharm_bucket is not None:
                radiopharm_bucket["missing_acquisition_time"] += 1

        patient_weight = get_patient_weight(row_dict)
        injected_activity = parse_db_float(row_dict.get('injected_activity'))
        if patient_weight is None:
            modality_bucket["missing_weight"] += 1
            if radiopharm_bucket is not None:
                radiopharm_bucket["missing_weight"] += 1
        if is_radiopharm_modality(modality) and not row_dict.get('injection_time'):
            modality_bucket["missing_injection_time"] += 1
            if radiopharm_bucket is not None:
                radiopharm_bucket["missing_injection_time"] += 1
        if patient_weight and injected_activity:
            activity_mbq = injected_activity / 1e6 if injected_activity > 1e6 else injected_activity
            dose_per_kg = activity_mbq / patient_weight
            if 0 < dose_per_kg < 100:
                doses_per_kg.append(dose_per_kg)
                modality_bucket["doses_per_kg"].append(dose_per_kg)
                if radiopharm_bucket is not None:
                    radiopharm_bucket["doses_per_kg"].append(dose_per_kg)

        series_time = row_dict.get('series_time')
        acquisition_time = row_dict.get('acquisition_time')
        if series_time and acquisition_time:
            series_sec = parse_time_to_24hour(series_time)
            acq_sec = parse_time_to_24hour(acquisition_time)
            if series_sec and acq_sec:
                duration = ((acq_sec[0] * 3600 + acq_sec[1] * 60 + acq_sec[2]) -
                            (series_sec[0] * 3600 + series_sec[1] * 60 + series_sec[2])) / 60
                if duration > 0:
                    scan_durations.append(duration)

        if is_radiopharm_modality(modality) and row_dict.get('radiopharmaceutical'):
            rad = row_dict['radiopharmaceutical']
            radiopharmaceuticals[rad] = radiopharmaceuticals.get(rad, 0) + 1
        if row_dict.get('manufacturer'):
            mfr = row_dict['manufacturer']
            manufacturers[mfr] = manufacturers.get(mfr, 0) + 1

        if row_dict.get('ctdivol') is not None or row_dict.get('dlp') is not None:
            ct_bucket = ct_dose_by_modality.setdefault(modality, {"ctdivol": [], "dlp": [], "count": 0})
            if row_dict.get('ctdivol') is not None:
                ct_bucket["ctdivol"].append(row_dict["ctdivol"])
            if row_dict.get('dlp') is not None:
                ct_bucket["dlp"].append(row_dict["dlp"])
            ct_bucket["count"] += 1

    def safe_float(value):
        return float(value) if value is not None else None

    def safe_stats(values):
        if not values:
            return {"count": 0, "mean": None, "median": None, "std_dev": None, "min": None, "max": None}
        return {
            "count": len(values),
            "mean": safe_float(statistics.mean(values)),
            "median": safe_float(statistics.median(values)),
            "std_dev": safe_float(statistics.stdev(values)) if len(values) > 1 else None,
            "min": safe_float(min(values)),
            "max": safe_float(max(values)),
        }

    total_series = len(representative_series_rows)
    total_studies = len(study_summary)
    redo_total = len(representative_series_rows)
    redo_with_repeats = 0

    def parse_age_years(value: Optional[object]) -> Optional[int]:
        if not value:
            return None
        text = str(value).strip()
        digits = "".join([c for c in text if c.isdigit()])
        if not digits:
            return None
        try:
            return int(digits)
        except ValueError:
            return None

    age_buckets = {"0-17": 0, "18-39": 0, "40-59": 0, "60-79": 0, "80+": 0}
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
            'within_ideal_range': len([t for t in uptake_times if 45 <= t <= 75]) if uptake_times else 0,
        },
        'dose_per_kg': {
            'count': len(doses_per_kg),
            'mean': safe_float(statistics.mean(doses_per_kg)) if doses_per_kg else None,
            'median': safe_float(statistics.median(doses_per_kg)) if doses_per_kg else None,
            'std_dev': safe_float(statistics.stdev(doses_per_kg)) if len(doses_per_kg) > 1 else None,
            'min': safe_float(min(doses_per_kg)) if doses_per_kg else None,
            'max': safe_float(max(doses_per_kg)) if doses_per_kg else None,
            'ideal': IDEAL_DOSE_PER_KG_MBQ,
            'within_ideal_range': len([d for d in doses_per_kg if 2.5 <= d <= 3.5]) if doses_per_kg else 0,
        },
        'radiopharmaceuticals': dict(sorted(radiopharmaceuticals.items(), key=lambda x: x[1], reverse=True)[:10]),
        'radiopharmaceutical_total_series': radiopharm_total_series,
        'manufacturers': dict(sorted(manufacturers.items(), key=lambda x: x[1], reverse=True)[:10]),
        'scan_duration': safe_stats(scan_durations),
        'redo_rate': {"total": redo_total, "repeats": redo_with_repeats},
        'missingness': {
            "weight": missing_weight,
            "height": missing_height,
            "birth_date": missing_birth_date,
            "series_weight": missing_series_weight,
            "series_injection_time": missing_series_injection,
            "series_acquisition_time": missing_series_acquisition,
        },
        'ctp_flagged': ctp_flagged,
        'sex_counts': sex_counts,
        'age_buckets': age_buckets,
        'study_dates': dict(sorted(study_dates.items(), reverse=True)[:10]),
        'study_hours': dict(sorted(study_hours.items())),
        'modality_summary': dict(sorted(modality_summary.items(), key=lambda x: x[1]["count"], reverse=True)),
        'radiopharm_summary': dict(sorted(radiopharm_summary.items(), key=lambda x: x[1]["count"], reverse=True)),
        'ct_summary': dict(sorted(ct_summary.items(), key=lambda x: x[1]["count"], reverse=True)),
    }

    csa_series_counts = {}
    for row in representative_series_rows:
        csa_series = row.get("csa_series_header_hash")
        if csa_series:
            csa_series_counts[csa_series] = csa_series_counts.get(csa_series, 0) + 1
    majority_csa = max(csa_series_counts, key=csa_series_counts.get) if csa_series_counts else None

    representative_study_uids = {row.get("study_instance_uid") for row in representative_series_rows if row.get("study_instance_uid")}
    study_total = len(representative_study_uids)
    completeness_counts = {
        "weight": 0, "dose": 0, "injection_time": 0, "acquisition_time": 0,
        "radiopharmaceutical": 0, "patient_sex": 0, "patient_age": 0,
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
            "dose": False, "injection_time": False, "acquisition_time": False, "radiopharmaceutical": False,
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

    timing_counts = {"negative": 0, "too_long": 0, "parse_fail": 0, "missing": 0, "study_time_conflict": 0}
    for row in representative_series_rows:
        _, status = compute_delay_status(row)
        if status in timing_counts:
            timing_counts[status] += 1
        if has_time_conflict(row):
            timing_counts["study_time_conflict"] += 1

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
        dose_per_kg, _ = compute_dose_from_row(row)
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

    scanner_groups = {}
    for row in representative_series_rows:
        key = (
            row.get("manufacturer") or "Unknown",
            row.get("manufacturer_model_name") or "Unknown",
            row.get("software_version") or "Unknown",
        )
        entry = scanner_groups.setdefault(key, {"count": 0, "csa_hashes": set()})
        entry["count"] += 1
        if row.get("csa_series_header_hash"):
            entry["csa_hashes"].add(row["csa_series_header_hash"])
    scanner_landscape = [
        {"manufacturer": key[0], "model": key[1], "software": key[2], "count": data["count"], "unique_csa": len(data["csa_hashes"])}
        for key, data in scanner_groups.items()
    ]
    scanner_landscape.sort(key=lambda x: x["count"], reverse=True)

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
        protocol_radiopharm.append({"radiopharmaceutical": radiopharm, "unique_fps": len(fp_counts), "top_fp": top_fp, "top_count": top_count})
    protocol_radiopharm.sort(key=lambda x: x["unique_fps"], reverse=True)

    derived_counts = {"seg": 0, "rtstruct": 0, "highdicom": 0, "qiicr": 0}
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
        representative_series_uids = [row.get("series_instance_uid") for row in representative_series_rows if row.get("series_instance_uid")]
        if representative_series_uids:
            conn = init_database(db_path, optimize=False)
            conn.row_factory = sqlite3.Row
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
            ctp_label_counts = [{"value_text": value_text, "count": count} for value_text, count in sorted(counts.items(), key=lambda x: x[1], reverse=True)[:10]]
    except sqlite3.Error:
        ctp_label_counts = []

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
            row.get("number_of_slices"),
        )
        series_signature_counts[signature] = series_signature_counts.get(signature, 0) + 1
    duplicate_series_signatures = sum(1 for count in series_signature_counts.values() if count > 1)

    study_series_counts = {row.get("study_instance_uid"): 1 for row in representative_series_rows if row.get("study_instance_uid")}
    studies_missing_ct = sum(1 for mods in study_modalities.values() if "PT" in mods and "CT" not in mods)
    studies_missing_pt = sum(1 for mods in study_modalities.values() if "CT" in mods and "PT" not in mods)
    studies_high_series = sum(1 for count in study_series_counts.values() if count > 20)

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
            "patient_age": study_total,
        },
    }
    dose_stats = {
        "outliers": dose_outliers,
        "unit_mismatch": possible_unit_mismatch,
        "missing_activity_has_weight": missing_activity_has_weight,
        "missing_weight_has_activity": missing_weight_has_activity,
        "total": radiopharm_dose_total,
        "mean": dose_mean,
        "std_dev": dose_std,
    }
    derived_stats = {
        "seg": derived_counts["seg"],
        "rtstruct": derived_counts["rtstruct"],
        "highdicom": derived_counts["highdicom"],
        "qiicr": derived_counts["qiicr"],
        "ctp_labels": ctp_label_counts,
    }
    duplicate_stats = {"duplicate_sop": duplicate_sop_count, "duplicate_series_signatures": duplicate_series_signatures}
    study_comp_stats = {"missing_ct": studies_missing_ct, "missing_pt": studies_missing_pt, "high_series": studies_high_series}

    def create_histogram(data, bins=20, min_val=None, max_val=None, precision=1, bin_width=None, max_bins=60):
        if not data:
            return {'labels': [], 'values': []}
        if min_val is None:
            min_val = float(min(data))
        if max_val is None:
            max_val = float(max(data))
        if max_val <= min_val:
            max_val = min_val + 1
        if bin_width:
            bins = int(math.ceil((max_val - min_val) / bin_width))
            bins = max(1, min(bins, max_bins))
        bin_width = (max_val - min_val) / bins
        histogram = [0] * bins
        labels = [f"{min_val + i * bin_width:.{precision}f}" for i in range(bins)]
        for value in data:
            val = float(value)
            if min_val <= val <= max_val:
                bin_index = min(int((val - min_val) / bin_width), bins - 1)
                histogram[bin_index] += 1
        return {'labels': labels, 'values': histogram}

    max_uptake = float(max(uptake_times)) if uptake_times else 180.0
    uptake_histogram = create_histogram(uptake_times, min_val=0, max_val=max_uptake, precision=1, bin_width=5, max_bins=60)
    max_dose = float(max(doses_per_kg)) if doses_per_kg else 10.0
    dose_histogram = create_histogram(doses_per_kg, min_val=0, max_val=max_dose, precision=2, bin_width=0.1, max_bins=80)

    return {
        "stats": stats,
        "uptake_histogram": {'labels': list(uptake_histogram['labels']), 'values': [int(v) for v in uptake_histogram['values']]},
        "dose_histogram": {'labels': list(dose_histogram['labels']), 'values': [int(v) for v in dose_histogram['values']]},
        "completeness_stats": completeness_stats,
        "timing_stats": timing_counts,
        "dose_stats": dose_stats,
        "scanner_landscape": scanner_landscape,
        "protocol_radiopharm": protocol_radiopharm,
        "derived_stats": derived_stats,
        "duplicate_stats": duplicate_stats,
        "study_comp_stats": study_comp_stats,
        "qa_scores": qa_scores,
    }

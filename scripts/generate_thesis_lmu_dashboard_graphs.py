#!/usr/bin/env python3
"""Generate dashboard distribution figures from a databank analytics payload."""

from __future__ import annotations

import argparse
import math
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-cache")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from dicom_browser.dashboard_service import build_dashboard_payload
from dicom_browser.export_utils import calculate_injection_delay
from webui import (
    compute_delay_status,
    compute_dose_from_row,
    has_radiopharm,
    has_time_conflict,
    load_representative_series,
    parse_time_to_24hour,
)

THESIS_DIR = ROOT / "efficient_data_access_and_storage_optimization_for_PET_CT_imaging_data"
DEFAULT_DB = Path("/tmp/lmu_psma_thesis.db")
OUTPUT_PATH = THESIS_DIR / "figures" / "graphs" / "lmu_dashboard_distributions.png"
PRIMARY_BLUE = "#163f7a"
SECONDARY_BLUE = "#9ecae1"
ACCENT_BLUE = "#4f97c9"
EDGE_COLOR = "#1f2d3d"
LIGHT_BLUE = "#dbeafe"
ORANGE_FILL = "#f4a261"
ORANGE_LIGHT = "#f6d7b0"
ORANGE_EDGE = "#c96f1a"


def default_dataset_label(db_path: Path) -> str:
    stem = db_path.stem
    if stem.endswith(".D50"):
        return stem.rsplit(".", 1)[-1]
    if stem.startswith("dicom_metadata_"):
        stem = stem.removeprefix("dicom_metadata_")
    elif stem.startswith("dicom_metadata"):
        stem = stem.removeprefix("dicom_metadata")
    cleaned = stem.strip("._-")
    return cleaned or db_path.stem


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("percentile() requires at least one value")
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower_index = int(math.floor(position))
    upper_index = int(math.ceil(position))
    if lower_index == upper_index:
        return ordered[lower_index]
    lower = ordered[lower_index]
    upper = ordered[upper_index]
    weight = position - lower_index
    return lower + (upper - lower) * weight


def round_up(value: float, step: float) -> float:
    return math.ceil(value / step) * step


def choose_plot_max(
    values: list[float],
    *,
    percentile_fraction: float,
    headroom: float,
    step: float,
    min_limit: float,
    max_limit: float,
) -> float:
    if not values:
        return max_limit
    robust_max = percentile(values, percentile_fraction) * headroom
    return min(max(round_up(robust_max, step), min_limit), max_limit)


def create_plot_histogram(
    values: list[float],
    *,
    max_val: float,
    precision: int,
    bin_width: float,
) -> tuple[dict, int]:
    if not values:
        return {"labels": [], "values": []}, 0

    bins = max(1, int(math.ceil(max_val / bin_width)))
    histogram = [0] * bins
    labels = [f"{i * bin_width:.{precision}f}" for i in range(bins)]
    omitted = 0

    for raw_value in values:
        value = float(raw_value)
        if value < 0:
            continue
        if value > max_val:
            omitted += 1
            continue
        bin_index = min(int(value / bin_width), bins - 1)
        histogram[bin_index] += 1

    return {"labels": labels, "values": histogram}, omitted


def collect_plot_data(representative_series_rows: list[dict]) -> dict:
    uptake_values = []
    dose_values = []

    for row in representative_series_rows:
        delay_minutes, _status = compute_delay_status(row)
        if delay_minutes is not None and delay_minutes > 0:
            uptake_values.append(float(delay_minutes))

        dose_per_kg, _ = compute_dose_from_row(row)
        if dose_per_kg is not None and 0 < dose_per_kg < 100:
            dose_values.append(float(dose_per_kg))

    uptake_plot_max = choose_plot_max(
        uptake_values,
        percentile_fraction=0.99,
        headroom=1.15,
        step=15.0,
        min_limit=120.0,
        max_limit=240.0,
    )
    dose_plot_max = choose_plot_max(
        dose_values,
        percentile_fraction=0.99,
        headroom=1.10,
        step=0.5,
        min_limit=4.0,
        max_limit=8.0,
    )

    uptake_histogram, uptake_omitted = create_plot_histogram(
        uptake_values,
        max_val=uptake_plot_max,
        precision=1,
        bin_width=5.0,
    )
    dose_histogram, dose_omitted = create_plot_histogram(
        dose_values,
        max_val=dose_plot_max,
        precision=2,
        bin_width=0.1,
    )

    return {
        "uptake_values": uptake_values,
        "dose_values": dose_values,
        "uptake_histogram": uptake_histogram,
        "dose_histogram": dose_histogram,
        "uptake_plot_max": uptake_plot_max,
        "dose_plot_max": dose_plot_max,
        "uptake_omitted": uptake_omitted,
        "dose_omitted": dose_omitted,
    }


def load_dashboard_payload(db_path: Path) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        study_summary = [
            dict(row)
            for row in conn.execute(
                """
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
                """
            )
        ]
        study_modalities = {
            row["study_instance_uid"]: set((row["modalities"] or "").split(","))
            for row in conn.execute(
                """
                SELECT
                    study_instance_uid,
                    GROUP_CONCAT(DISTINCT modality) as modalities
                FROM dicom_metadata
                GROUP BY study_instance_uid
                """
            )
            if row["study_instance_uid"]
        }
        _, representative_series_rows = load_representative_series(conn)
    finally:
        conn.close()

    payload = build_dashboard_payload(
        study_summary=study_summary,
        study_modalities=study_modalities,
        representative_series_rows=representative_series_rows,
        db_path=str(db_path),
        parse_time_to_24hour=parse_time_to_24hour,
        calculate_injection_delay=calculate_injection_delay,
        compute_delay_status=compute_delay_status,
        has_time_conflict=has_time_conflict,
        has_radiopharm=has_radiopharm,
    )
    payload["_plot_data"] = collect_plot_data(representative_series_rows)
    return payload


def histogram_positions(histogram: dict) -> tuple[list[float], float]:
    labels = [float(label) for label in histogram["labels"]]
    if len(labels) > 1:
        width = labels[1] - labels[0]
    else:
        width = 1.0
    return labels, width


def add_distribution_panel(
    ax,
    *,
    histogram: dict,
    stats: dict,
    title: str,
    xlabel: str,
    ideal_label: str,
    ideal_value: float,
    ideal_band: tuple[float, float],
    bar_fill: str,
    bar_edge: str,
    band_fill: str,
    decimals: int,
    x_limit: float,
    omitted_count: int,
) -> None:
    x_positions, bin_width = histogram_positions(histogram)
    values = histogram["values"]

    ax.set_facecolor("white")
    ax.axvspan(ideal_band[0], ideal_band[1], color=band_fill, alpha=0.65, zorder=0)
    ax.bar(
        x_positions,
        values,
        width=bin_width * 0.92,
        align="edge",
        color=bar_fill,
        edgecolor=bar_edge,
        linewidth=0.8,
        zorder=2,
    )
    ax.axvline(ideal_value, color=bar_edge, linestyle="--", linewidth=1.8, zorder=3)
    ax.set_title(title, fontsize=12, fontweight="bold", loc="center")
    ax.set_xlabel(xlabel, fontsize=10)
    ax.set_ylabel("Study count", fontsize=10)
    ax.set_xlim(0, x_limit)
    ax.grid(axis="y", color="#d1d5db", linewidth=0.8, alpha=0.7, zorder=1)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(labelsize=9)

    within_pct = (stats["within_ideal_range"] / stats["count"] * 100) if stats["count"] else 0
    summary = (
        f"{ideal_label}: {ideal_value:.{decimals}f}\n"
        f"Mean: {stats['mean']:.{decimals}f}\n"
        f"Median: {stats['median']:.{decimals}f}\n"
        f"Range: {stats['min']:.{decimals}f}-{stats['max']:.{decimals}f}\n"
        f"Within target: {stats['within_ideal_range']}/{stats['count']} ({within_pct:.1f}%)"
    )
    if omitted_count:
        summary += f"\nExcluded beyond displayed range: {omitted_count}"
    ax.text(
        0.985,
        0.97,
        summary,
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=9,
        color="black",
    )


def add_adherence_panel(ax, *, uptake_stats: dict, dose_stats: dict, title_label: str, axis_label: str) -> None:
    uptake_pct = (uptake_stats["within_ideal_range"] / uptake_stats["count"] * 100) if uptake_stats["count"] else 0
    dose_pct = (dose_stats["within_ideal_range"] / dose_stats["count"] * 100) if dose_stats["count"] else 0

    ax.set_facecolor("white")
    ax.set_xlim(0, 100)
    ax.set_ylim(-0.8, 1.8)
    ax.set_title(title_label, fontsize=13, fontweight="bold", loc="center")

    labels = [
        "Injection-to-scan time within 45-75 min",
        "Injected dose within 2.5-3.5 MBq/kg",
    ]
    percents = [uptake_pct, dose_pct]
    counts = [
        f"{uptake_stats['within_ideal_range']}/{uptake_stats['count']}",
        f"{dose_stats['within_ideal_range']}/{dose_stats['count']}",
    ]
    fills = [PRIMARY_BLUE, ORANGE_FILL]
    tracks = [LIGHT_BLUE, ORANGE_LIGHT]
    y_positions = [1, 0]

    for y, label, pct, count, fill, track in zip(y_positions, labels, percents, counts, fills, tracks):
        ax.barh(y, 100, height=0.34, color=track, edgecolor="none", zorder=1)
        ax.barh(y, pct, height=0.34, color=fill, edgecolor="none", zorder=2)
        ax.text(0, y + 0.28, label, ha="left", va="bottom", fontsize=10, color="black", fontweight="semibold")
        ax.text(
            min(pct + 1.2, 99.2),
            y,
            f"{pct:.1f}% ({count})",
            ha="left" if pct < 92 else "right",
            va="center",
            fontsize=9,
            color="black",
        )

    ax.set_yticks([])
    ax.set_xlabel(axis_label, fontsize=10)
    ax.grid(axis="x", color="#d1d5db", linewidth=0.8, alpha=0.7)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="x", labelsize=9)


def render_figure(
    payload: dict,
    output_path: Path,
    dataset_label: str,
    *,
    overall_title: str | None = None,
    adherence_title: str | None = None,
    adherence_axis_label: str | None = None,
    include_dataset_in_hist_titles: bool = True,
) -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "axes.titlepad": 10,
        }
    )

    fig = plt.figure(figsize=(12.8, 7.6), constrained_layout=True)
    grid = fig.add_gridspec(2, 2, height_ratios=[0.85, 1.75])
    adherence_ax = fig.add_subplot(grid[0, :])
    uptake_ax = fig.add_subplot(grid[1, 0])
    dose_ax = fig.add_subplot(grid[1, 1])
    fig.patch.set_facecolor("white")
    plot_data = payload["_plot_data"]

    dataset_title = dataset_label or "Dashboard"
    add_adherence_panel(
        adherence_ax,
        uptake_stats=payload["stats"]["uptake_time"],
        dose_stats=payload["stats"]["dose_per_kg"],
        title_label=adherence_title or f"{dataset_title}: Protocol Adherence",
        axis_label=adherence_axis_label or f"Share of representative {dataset_title} studies",
    )
    uptake_title = "Injection-to-Scan Time Distribution"
    dose_title = "Injected Dose per kg Distribution"
    if include_dataset_in_hist_titles:
        uptake_title = f"{dataset_title}: {uptake_title}"
        dose_title = f"{dataset_title}: {dose_title}"
    add_distribution_panel(
        uptake_ax,
        histogram=plot_data["uptake_histogram"],
        stats=payload["stats"]["uptake_time"],
        title=uptake_title,
        xlabel="Minutes after injection",
        ideal_label="Dashboard ideal",
        ideal_value=float(payload["stats"]["uptake_time"]["ideal"]),
        ideal_band=(45.0, 75.0),
        bar_fill=SECONDARY_BLUE,
        bar_edge=PRIMARY_BLUE,
        band_fill=LIGHT_BLUE,
        decimals=1,
        x_limit=float(plot_data["uptake_plot_max"]),
        omitted_count=int(plot_data["uptake_omitted"]),
    )
    add_distribution_panel(
        dose_ax,
        histogram=plot_data["dose_histogram"],
        stats=payload["stats"]["dose_per_kg"],
        title=dose_title,
        xlabel="Dose (MBq/kg)",
        ideal_label="Dashboard ideal",
        ideal_value=float(payload["stats"]["dose_per_kg"]["ideal"]),
        ideal_band=(2.5, 3.5),
        bar_fill=ORANGE_FILL,
        bar_edge=ORANGE_EDGE,
        band_fill=ORANGE_LIGHT,
        decimals=2,
        x_limit=float(plot_data["dose_plot_max"]),
        omitted_count=int(plot_data["dose_omitted"]),
    )
    fig.suptitle(
        overall_title or f"Dashboard-derived {dataset_title} representative-series distributions",
        fontsize=14,
        fontweight="bold",
        color="black",
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate dashboard adherence and distribution histograms from a databank."
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help=f"SQLite databank to visualize (default: {DEFAULT_DB})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
        help=f"Output PNG path (default: {OUTPUT_PATH})",
    )
    parser.add_argument(
        "--label",
        default=None,
        help="Dataset label to use in the figure title. Defaults to a label derived from the database filename.",
    )
    parser.add_argument(
        "--overall-title",
        default=None,
        help="Optional full figure title override.",
    )
    parser.add_argument(
        "--adherence-title",
        default=None,
        help="Optional adherence panel title override.",
    )
    parser.add_argument(
        "--adherence-axis-label",
        default=None,
        help="Optional adherence panel x-axis label override.",
    )
    parser.add_argument(
        "--plain-histogram-titles",
        action="store_true",
        help="Use histogram titles without the dataset label prefix.",
    )
    args = parser.parse_args()

    db_path = args.db.resolve()
    output_path = args.output.resolve()
    dataset_label = args.label or default_dataset_label(db_path)

    payload = load_dashboard_payload(db_path)
    render_figure(
        payload,
        output_path,
        dataset_label,
        overall_title=args.overall_title,
        adherence_title=args.adherence_title,
        adherence_axis_label=args.adherence_axis_label,
        include_dataset_in_hist_titles=not args.plain_histogram_titles,
    )
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()

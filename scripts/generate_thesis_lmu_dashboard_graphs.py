#!/usr/bin/env python3
"""Generate thesis figures from the LMU dashboard analytics payload."""

from __future__ import annotations

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

    return build_dashboard_payload(
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


def add_adherence_panel(ax, *, uptake_stats: dict, dose_stats: dict) -> None:
    uptake_pct = (uptake_stats["within_ideal_range"] / uptake_stats["count"] * 100) if uptake_stats["count"] else 0
    dose_pct = (dose_stats["within_ideal_range"] / dose_stats["count"] * 100) if dose_stats["count"] else 0

    ax.set_facecolor("white")
    ax.set_xlim(0, 100)
    ax.set_ylim(-0.8, 1.8)
    ax.set_title("LMU_PSMA: Protocol Adherence", fontsize=13, fontweight="bold", loc="center")

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
    ax.set_xlabel("Share of representative LMU studies", fontsize=10)
    ax.grid(axis="x", color="#d1d5db", linewidth=0.8, alpha=0.7)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="x", labelsize=9)


def render_figure(payload: dict, output_path: Path) -> None:
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

    add_adherence_panel(
        adherence_ax,
        uptake_stats=payload["stats"]["uptake_time"],
        dose_stats=payload["stats"]["dose_per_kg"],
    )
    add_distribution_panel(
        uptake_ax,
        histogram=payload["uptake_histogram"],
        stats=payload["stats"]["uptake_time"],
        title="LMU_PSMA: Injection-to-Scan Time Distribution",
        xlabel="Minutes after injection",
        ideal_label="Dashboard ideal",
        ideal_value=float(payload["stats"]["uptake_time"]["ideal"]),
        ideal_band=(45.0, 75.0),
        bar_fill=SECONDARY_BLUE,
        bar_edge=PRIMARY_BLUE,
        band_fill=LIGHT_BLUE,
        decimals=1,
    )
    add_distribution_panel(
        dose_ax,
        histogram=payload["dose_histogram"],
        stats=payload["stats"]["dose_per_kg"],
        title="LMU_PSMA: Injected Dose per kg Distribution",
        xlabel="Dose (MBq/kg)",
        ideal_label="Dashboard ideal",
        ideal_value=float(payload["stats"]["dose_per_kg"]["ideal"]),
        ideal_band=(2.5, 3.5),
        bar_fill=ORANGE_FILL,
        bar_edge=ORANGE_EDGE,
        band_fill=ORANGE_LIGHT,
        decimals=2,
    )
    fig.suptitle(
        "Dashboard-derived LMU representative-series distributions",
        fontsize=14,
        fontweight="bold",
        color="black",
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    payload = load_dashboard_payload(DEFAULT_DB)
    render_figure(payload, OUTPUT_PATH)
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

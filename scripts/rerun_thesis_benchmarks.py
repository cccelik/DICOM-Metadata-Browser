#!/usr/bin/env python3
"""Rerun thesis benchmarks and regenerate Chapter 4 graph assets."""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import statistics
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from dicom_browser.qa_utils import calculate_raw_injection_delay_minutes

THESIS_DIR = ROOT / "Efficient Data Access and Storage Optimization for PET:CT Imaging Data"
GRAPH_DIR = THESIS_DIR / "figures" / "graphs"
TMP_DIR = Path("/tmp")

MB = 1_000_000
MIB = 1024 * 1024
WORKERS = 8
REPEATS = 5


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    raw_dir: Path
    filtered_dir: Path


DATASETS = [
    DatasetSpec(
        "AnonAxilla",
        ROOT / "scans" / "allScans" / "AnonAxilla",
        ROOT / "scans" / "allScans" / "AnonAxillaFiltered",
    ),
    DatasetSpec(
        "MIRROR_A",
        ROOT / "scans" / "allScans" / "MIRROR_A",
        TMP_DIR / "one_per_series_allscans_MIRROR_A",
    ),
    DatasetSpec(
        "PPA",
        ROOT / "scans" / "allScans" / "PPAnew",
        TMP_DIR / "one_per_series_allscans_PPA",
    ),
    DatasetSpec(
        "LMU_PSMA",
        ROOT / "scans" / "allScans" / "LMU_PSMA",
        ROOT / "scans" / "allScans" / "LMU_PSMA_Filtered",
    ),
]

TIME_RE = re.compile(r"Elapsed time:\s*([0-9.]+)s")
EXTRACT_RE = re.compile(r"extract_metadata_s:\s*([0-9.]+)s")
INSERT_RE = re.compile(r"insert_metadata_s:\s*([0-9.]+)s")
RSS_RE = re.compile(r"^\s*([0-9]+)\s+maximum resident set size$", re.MULTILINE)


def ensure_filtered_inputs() -> None:
    targets = [
        (
            ROOT / "scans" / "allScans" / "MIRROR_A",
            TMP_DIR / "one_per_series_allscans_MIRROR_A",
        ),
        (
            ROOT / "scans" / "allScans" / "PPAnew",
            TMP_DIR / "one_per_series_allscans_PPA",
        ),
    ]
    for source, target in targets:
        if target.exists():
            continue
        run(
            [
                "python3",
                "extract_one_per_series.py",
                str(source),
                str(target),
            ],
            cwd=ROOT,
        )


def run(cmd: list[str], cwd: Path) -> str:
    result = subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed ({result.returncode}): {' '.join(cmd)}\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result.stdout + result.stderr


def run_timed_process(input_dir: Path, output_db: Path, extra_args: list[str] | None = None) -> dict[str, Any]:
    if output_db.exists():
        output_db.unlink()
    if output_db.with_suffix(output_db.suffix + "-wal").exists():
        output_db.with_suffix(output_db.suffix + "-wal").unlink()
    if output_db.with_suffix(output_db.suffix + "-shm").exists():
        output_db.with_suffix(output_db.suffix + "-shm").unlink()

    cmd = [
        "/usr/bin/time",
        "-l",
        "python3",
        "process_dicom.py",
        str(input_dir),
        str(output_db),
        "--no-subdirs",
        "--timing",
        "--max-workers",
        str(WORKERS),
    ]
    if extra_args:
        cmd.extend(extra_args)
    output = run(cmd, cwd=ROOT)
    return parse_timed_output(output)


def parse_timed_output(output: str) -> dict[str, float]:
    elapsed = extract_float(TIME_RE, output)
    extract = extract_float(EXTRACT_RE, output)
    insert = extract_float(INSERT_RE, output)
    rss_bytes = extract_int(RSS_RE, output)
    return {
        "elapsed_s": elapsed,
        "extract_s": extract,
        "insert_s": insert,
        "peak_rss_mib": rss_bytes / MIB,
    }


def extract_float(pattern: re.Pattern[str], text: str) -> float:
    match = pattern.search(text)
    if not match:
        raise ValueError(f"Could not parse float with {pattern.pattern!r}")
    return float(match.group(1))


def extract_int(pattern: re.Pattern[str], text: str) -> int:
    match = pattern.search(text)
    if not match:
        raise ValueError(f"Could not parse int with {pattern.pattern!r}")
    return int(match.group(1))


def dir_size_bytes(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            file_path = Path(root) / name
            try:
                total += file_path.stat().st_size
            except FileNotFoundError:
                pass
    return total


def db_metrics(db_path: Path) -> dict[str, Any]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(row) for row in conn.execute("SELECT * FROM dicom_metadata")]

    quality = {
        "processed_instances": len(rows),
        "radiopharmaceutical": 0,
        "dose": 0,
        "inj_time": 0,
        "acq_time": 0,
        "valid_delay": 0,
        "negative": 0,
        "over_180": 0,
    }

    for row in rows:
        if row.get("radiopharmaceutical"):
            quality["radiopharmaceutical"] += 1
        if row.get("injected_activity") is not None:
            quality["dose"] += 1
        if row.get("injection_time"):
            quality["inj_time"] += 1
        if row.get("acquisition_time"):
            quality["acq_time"] += 1
        delay = calculate_raw_injection_delay_minutes(
            row.get("injection_date") or row.get("study_date"),
            row.get("injection_time"),
            row.get("acquisition_date") or row.get("study_date"),
            row.get("acquisition_time"),
        )
        if delay is not None:
            quality["valid_delay"] += 1
            if delay < 0:
                quality["negative"] += 1
            if delay > 180:
                quality["over_180"] += 1

    return {
        "db_bytes": db_path.stat().st_size,
        **quality,
    }


def reduction_metrics(raw_bytes: int, filtered_bytes: int, db_bytes: int) -> dict[str, float]:
    return {
        "raw_to_filtered_pct": (1 - (filtered_bytes / raw_bytes)) * 100,
        "filtered_to_db_pct": (1 - (db_bytes / filtered_bytes)) * 100,
        "raw_to_db_pct": (1 - (db_bytes / raw_bytes)) * 100,
        "raw_to_db_x": raw_bytes / db_bytes,
    }


def regen_graphs(results: dict[str, Any]) -> None:
    GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    sns.set_theme(
        style="whitegrid",
        rc={
            "axes.facecolor": "#ffffff",
            "figure.facecolor": "#ffffff",
            "grid.color": "#d9d9d9",
            "grid.linestyle": ":",
            "axes.edgecolor": "#333333",
        },
    )
    primary_blue = "#163f7a"
    secondary_blue = "#9ecae1"
    accent_blue = "#4f97c9"

    filtered_df = pd.DataFrame(results["filtered"]).set_index("dataset")
    reductions_df = pd.DataFrame(results["reductions"]).set_index("dataset")
    quality_df = pd.DataFrame(results["quality"]).set_index("dataset")
    raw_vs_filtered_df = pd.DataFrame(results["raw_vs_filtered"]).set_index("dataset")

    fig, ax = plt.subplots(figsize=(8.0, 4.6))
    bar_plot = filtered_df["elapsed_s"].plot(kind="bar", ax=ax, color=primary_blue, edgecolor="#1f2d3d")
    ax.set_title("Total Runtime by Dataset")
    ax.set_ylabel("Total runtime (s)")
    ax.set_xlabel("")
    ax.tick_params(axis="x", rotation=0)
    for patch, value in zip(bar_plot.patches, filtered_df["elapsed_s"]):
        ax.text(
            patch.get_x() + patch.get_width() / 2,
            patch.get_height() + max(filtered_df["elapsed_s"]) * 0.015,
            f"{value:.2f}s",
            ha="center",
            va="bottom",
            fontsize=9,
            color=primary_blue,
        )
    fig.tight_layout()
    fig.savefig(GRAPH_DIR / "runtime_breakdown.png", dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.0, 4.6))
    bar_plot = reductions_df["raw_to_db_x"].plot(kind="bar", ax=ax, color=accent_blue, edgecolor="#3a5875")
    ax.set_title("Overall Storage Reduction Factor (Raw \u2192 DB)")
    ax.set_ylabel("Reduction factor (x)")
    ax.set_xlabel("")
    ax.set_yscale("log")
    ax.tick_params(axis="x", rotation=0)
    for patch, value in zip(bar_plot.patches, reductions_df["raw_to_db_x"]):
        ax.text(
            patch.get_x() + patch.get_width() / 2,
            value * 1.08,
            f"{value:.1f}x",
            ha="center",
            va="bottom",
            fontsize=9,
            color=primary_blue,
        )
    fig.tight_layout()
    fig.savefig(GRAPH_DIR / "storage_reduction.png", dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.2, 4.6))
    heatmap_data = quality_df[
        ["radiopharmaceutical", "dose", "inj_time", "acq_time", "valid_delay"]
    ]
    sns.heatmap(
        heatmap_data,
        annot=True,
        fmt=".0f",
        cmap="Blues",
        cbar=True,
        cbar_kws={"label": "Count"},
        ax=ax,
        annot_kws={"fontsize": 10, "fontweight": "bold"},
    )
    ax.set_title("QA Field Completeness (Counts)")
    ax.set_xlabel("")
    ax.set_ylabel("")
    ax.set_xticklabels(["Radiopharm", "Dose", "Inj time", "Acq time", "Valid delay"], rotation=20, ha="right")
    ax.tick_params(axis="y", rotation=0)
    fig.tight_layout()
    fig.savefig(GRAPH_DIR / "qa_completeness.png", dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.0, 4.6))
    anomaly_data = quality_df[["negative", "over_180"]].copy()
    anomaly_data.columns = ["Negative delays", "Delays > 180 min"]
    anomaly_plot = anomaly_data.plot(kind="bar", ax=ax, color=[primary_blue, secondary_blue], edgecolor="#1f2d3d")
    for patch in anomaly_plot.patches[len(quality_df):]:
        patch.set_hatch("//")
    ax.set_title("Temporal Delay Anomalies")
    ax.set_ylabel("Count")
    ax.set_xlabel("")
    ax.tick_params(axis="x", rotation=0)
    ax.legend(frameon=True)
    fig.tight_layout()
    fig.savefig(GRAPH_DIR / "delay_anomalies.png", dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.2, 4.8))
    throughput_df = filtered_df.join(pd.DataFrame(results["sizes"]).set_index("dataset")[["raw_mb", "processed_instances"]])
    throughput_df["instances_per_s"] = throughput_df["processed_instances"] / throughput_df["elapsed_s"]
    ax.scatter(
        throughput_df["raw_mb"],
        throughput_df["instances_per_s"],
        s=130,
        color="#2b83ba",
        edgecolors=primary_blue,
        linewidths=1.2,
    )
    for dataset, row in throughput_df.iterrows():
        if dataset == "PPA":
            offset_x, offset_y, ha = 8, -18, "left"
        elif dataset == "LMU_PSMA":
            offset_x, offset_y, ha = -10, 8, "right"
        else:
            offset_x, offset_y, ha = 8, 8, "left"
        ax.annotate(
            dataset,
            (row["raw_mb"], row["instances_per_s"]),
            xytext=(offset_x, offset_y),
            textcoords="offset points",
            fontsize=10,
            fontweight="bold",
            ha=ha,
        )
    ax.set_title("Throughput vs Dataset Size (log-x)")
    ax.set_xscale("log")
    ax.set_xlabel("Dataset size (MB)")
    ax.set_ylabel("Instances/s")
    fig.tight_layout()
    fig.savefig(GRAPH_DIR / "throughput_vs_size.png", dpi=180)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(12.0, 5.0))
    runtime_plot = raw_vs_filtered_df[["raw_time_s", "filtered_time_s"]].copy()
    runtime_plot.columns = ["Raw", "Filtered"]
    runtime_plot.plot(kind="bar", ax=axes[0], color=[primary_blue, secondary_blue], edgecolor="#1f2d3d")
    for patch in axes[0].patches[len(raw_vs_filtered_df):]:
        patch.set_hatch("//")
    axes[0].set_title("Raw vs Filtered Runtime")
    axes[0].set_yscale("log")
    axes[0].set_ylabel("Runtime (s, log scale)")
    axes[0].set_xlabel("")
    axes[0].tick_params(axis="x", rotation=20)
    axes[0].legend(frameon=True)
    memory_plot = raw_vs_filtered_df[["raw_rss_mib", "filtered_rss_mib"]].copy()
    memory_plot.columns = ["Raw", "Filtered"]
    memory_plot.plot(kind="bar", ax=axes[1], color=[primary_blue, secondary_blue], edgecolor="#1f2d3d")
    for patch in axes[1].patches[len(raw_vs_filtered_df):]:
        patch.set_hatch("//")
    axes[1].set_title("Raw vs Filtered Memory")
    axes[1].set_ylabel("Peak RSS (MiB)")
    axes[1].set_xlabel("")
    axes[1].tick_params(axis="x", rotation=20)
    fig.tight_layout()
    fig.savefig(GRAPH_DIR / "raw_vs_filtered_runtime_memory.png", dpi=180)
    plt.close(fig)


def round2(value: float) -> float:
    return round(value + 1e-12, 2)


def round1(value: float) -> float:
    return round(value + 1e-12, 1)


def main() -> None:
    ensure_filtered_inputs()

    sizes: list[dict[str, Any]] = []
    filtered_results: list[dict[str, Any]] = []
    reductions: list[dict[str, Any]] = []
    quality_rows: list[dict[str, Any]] = []
    raw_vs_filtered: list[dict[str, Any]] = []
    repeatability: list[dict[str, Any]] = []

    for spec in DATASETS:
        raw_bytes = dir_size_bytes(spec.raw_dir)
        filtered_bytes = dir_size_bytes(spec.filtered_dir)

        filtered_db = TMP_DIR / f"thesis_filtered_{spec.name.lower()}.db"
        filtered_timing = run_timed_process(spec.filtered_dir, filtered_db)
        filtered_quality = db_metrics(filtered_db)
        db_mb = filtered_quality["db_bytes"] / MB

        sizes.append(
            {
                "dataset": spec.name,
                "raw_mb": round2(raw_bytes / MB),
                "filtered_mb": round2(filtered_bytes / MB),
                "db_mb": round2(db_mb),
                "processed_instances": filtered_quality["processed_instances"],
            }
        )
        filtered_results.append(
            {
                "dataset": spec.name,
                "elapsed_s": round2(filtered_timing["elapsed_s"]),
                "extract_s": round2(filtered_timing["extract_s"]),
                "insert_s": round2(filtered_timing["insert_s"]),
                "peak_rss_mib": round1(filtered_timing["peak_rss_mib"]),
                "filtered_mb": round2(filtered_bytes / MB),
                "db_mb": round2(db_mb),
            }
        )
        reductions.append(
            {
                "dataset": spec.name,
                **{
                    key: round1(value) if key.endswith("_pct") else round1(value)
                    for key, value in reduction_metrics(raw_bytes, filtered_bytes, filtered_quality["db_bytes"]).items()
                },
            }
        )
        quality_rows.append(
            {
                "dataset": spec.name,
                "radiopharmaceutical": filtered_quality["radiopharmaceutical"],
                "dose": filtered_quality["dose"],
                "inj_time": filtered_quality["inj_time"],
                "acq_time": filtered_quality["acq_time"],
                "valid_delay": filtered_quality["valid_delay"],
                "negative": filtered_quality["negative"],
                "over_180": filtered_quality["over_180"],
            }
        )

        raw_db = TMP_DIR / f"thesis_raw_{spec.name.lower()}.db"
        raw_timing = run_timed_process(spec.raw_dir, raw_db)
        raw_quality = db_metrics(raw_db)
        filtered_pair_db = TMP_DIR / f"thesis_pair_filtered_{spec.name.lower()}.db"
        filtered_pair_timing = run_timed_process(spec.filtered_dir, filtered_pair_db)
        filtered_pair_quality = db_metrics(filtered_pair_db)
        raw_vs_filtered.append(
            {
                "dataset": spec.name,
                "raw_time_s": round2(raw_timing["elapsed_s"]),
                "filtered_time_s": round2(filtered_pair_timing["elapsed_s"]),
                "raw_rss_mib": round1(raw_timing["peak_rss_mib"]),
                "filtered_rss_mib": round1(filtered_pair_timing["peak_rss_mib"]),
                "raw_db_mb": round2(raw_quality["db_bytes"] / MB),
                "filtered_db_mb": round2(filtered_pair_quality["db_bytes"] / MB),
            }
        )

        repeat_times = []
        for index in range(REPEATS):
            repeat_db = TMP_DIR / f"thesis_repeat_{spec.name.lower()}_{index + 1}.db"
            repeat_timing = run_timed_process(
                spec.filtered_dir,
                repeat_db,
                extra_args=["--no-auto-workers"],
            )
            repeat_times.append(repeat_timing["elapsed_s"])
        mean_runtime = statistics.mean(repeat_times)
        std_runtime = statistics.stdev(repeat_times) if len(repeat_times) > 1 else 0.0
        repeatability.append(
            {
                "dataset": spec.name,
                "mean_runtime_s": round2(mean_runtime),
                "std_runtime_s": round2(std_runtime),
                "cv_pct": round1((std_runtime / mean_runtime) * 100 if mean_runtime else 0.0),
                "runs_s": [round2(value) for value in repeat_times],
            }
        )

    results = {
        "sizes": sizes,
        "filtered": filtered_results,
        "reductions": reductions,
        "quality": quality_rows,
        "raw_vs_filtered": raw_vs_filtered,
        "repeatability": repeatability,
    }

    regen_graphs(results)
    output_path = THESIS_DIR / "benchmark_results.json"
    output_path.write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()

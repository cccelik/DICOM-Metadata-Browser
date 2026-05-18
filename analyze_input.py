#!/usr/bin/env python3
"""Analyze input size and oversized DICOM-like data with CLI progress."""

import argparse
import json
from pathlib import Path

from dicom_browser.dicom_discovery import (
    analyze_7z_size,
    analyze_input_size,
    analyze_zip_size,
    max_file_mb_to_bytes,
)
from dicom_browser.progress import TerminalProgress


def _print_summary(analysis: dict) -> None:
    print(f"Input: {analysis.get('path', '')}")
    print(f"Threshold: {analysis.get('threshold', '')}")
    print(f"Total files: {analysis.get('total_files', 0)}")
    print(f"Total size: {analysis.get('total_size', '')}")
    print(f"Candidate files: {analysis.get('candidate_files', 0)}")
    print(f"Candidate size: {analysis.get('candidate_size', '')}")
    print(
        "Oversized DICOM-like: "
        f"{analysis.get('oversized_dicom_like_files', 0)} files / "
        f"{analysis.get('oversized_dicom_like_size', '')}"
    )
    print(f"Estimated raw-like: {float(analysis.get('estimated_raw_like_percent') or 0.0):.1f}%")
    print(f"Skipped by threshold: {float(analysis.get('skipped_by_threshold_percent') or 0.0):.1f}%")
    largest = analysis.get("largest_oversized") or []
    if largest:
        print("Largest oversized files:")
        for item in largest[:10]:
            print(f"  {item.get('size', '')}  {item.get('path', '')}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze DICOM input size and estimate oversized/raw-like data."
    )
    parser.add_argument("input_path", help="Input folder, file, or ZIP archive to analyze.")
    parser.add_argument(
        "--max-file-mb",
        type=float,
        default=100.0,
        help="Threshold in MB for oversized classification. Use 0 for no size limit.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full analysis as JSON after progress completes.",
    )
    args = parser.parse_args()
    if args.max_file_mb < 0:
        parser.error("--max-file-mb must be zero or greater")

    input_path = Path(args.input_path).expanduser().resolve()
    max_file_bytes = max_file_mb_to_bytes(args.max_file_mb)
    progress = TerminalProgress("analyze_input")
    if input_path.is_file() and input_path.suffix.lower() == ".zip":
        analysis = analyze_zip_size(input_path, max_file_bytes=max_file_bytes, progress_callback=progress)
    elif input_path.is_file() and input_path.suffix.lower() == ".7z":
        analysis = analyze_7z_size(input_path, max_file_bytes=max_file_bytes, progress_callback=progress)
    else:
        analysis = analyze_input_size(input_path, max_file_bytes=max_file_bytes, progress_callback=progress)

    if not analysis.get("exists"):
        raise SystemExit(str(analysis.get("message", "Input path does not exist.")))
    if args.json:
        print(json.dumps(analysis, indent=2))
    else:
        _print_summary(analysis)


if __name__ == "__main__":
    main()

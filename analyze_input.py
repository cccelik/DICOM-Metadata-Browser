#!/usr/bin/env python3
"""Analyze input size and oversized DICOM-like data with CLI progress."""

import argparse
import json

from dicom_browser.cli_paths import expand_path_patterns
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
    parser.add_argument(
        "input_paths",
        nargs="+",
        help="Input folder, file, ZIP/7Z archive, or wildcard pattern to analyze.",
    )
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

    input_paths = expand_path_patterns(args.input_paths)
    if not input_paths:
        parser.error("No input paths matched")
    max_file_bytes = max_file_mb_to_bytes(args.max_file_mb)
    analyses = []
    for index, input_path in enumerate(input_paths, start=1):
        if len(input_paths) > 1 and not args.json:
            print(f"\n=== Input {index}/{len(input_paths)}: {input_path} ===")
        progress = TerminalProgress("analyze_input")
        if input_path.is_file() and input_path.suffix.lower() == ".zip":
            analysis = analyze_zip_size(input_path, max_file_bytes=max_file_bytes, progress_callback=progress)
        elif input_path.is_file() and input_path.suffix.lower() == ".7z":
            analysis = analyze_7z_size(input_path, max_file_bytes=max_file_bytes, progress_callback=progress)
        else:
            analysis = analyze_input_size(input_path, max_file_bytes=max_file_bytes, progress_callback=progress)

        if not analysis.get("exists"):
            raise SystemExit(str(analysis.get("message", "Input path does not exist.")))
        analyses.append(analysis)
    if args.json:
        payload = analyses[0] if len(analyses) == 1 else analyses
        print(json.dumps(payload, indent=2))
    else:
        for analysis in analyses:
            _print_summary(analysis)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Extract one DICOM file per series, then process the sampled output into a databank.
"""

import argparse
import re
import time
from pathlib import Path
from typing import Optional

from dicom_browser.dicom_discovery import DEFAULT_MAX_FILE_BYTES, max_file_mb_to_bytes
from dicom_browser.extract_metadata import DEFAULT_PARTIAL_READ_BYTES
from dicom_browser.progress import TerminalProgress
from extract_one_per_series import extract_one_per_series
from process_dicom import DEFAULT_DB_NAME, process_directory

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_SAMPLE_ROOT = BASE_DIR / "OnePerSeriesSamples"


def _safe_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return name.strip("._") or "dicom_input"


def _default_output_root(input_path: Path) -> Path:
    stem = input_path.stem if input_path.is_file() else input_path.name
    base = DEFAULT_SAMPLE_ROOT / f"{_safe_name(stem)}_samples"
    if not base.exists():
        return base
    index = 2
    while True:
        candidate = DEFAULT_SAMPLE_ROOT / f"{_safe_name(stem)}_samples_{index}"
        if not candidate.exists():
            return candidate
        index += 1


def _parse_non_negative_mb(parser: argparse.ArgumentParser, value: float, option: str) -> Optional[int]:
    if value < 0:
        parser.error(f"{option} must be zero or greater")
    return max_file_mb_to_bytes(value)


def _parse_positive_mb(parser: argparse.ArgumentParser, value: float, option: str) -> int:
    if value <= 0:
        parser.error(f"{option} must be greater than zero")
    return max_file_mb_to_bytes(value) or DEFAULT_PARTIAL_READ_BYTES


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run one-per-series extraction and DICOM metadata processing in one command."
    )
    parser.add_argument(
        "input_path",
        help="Input folder or ZIP archive containing DICOM data.",
    )
    parser.add_argument(
        "db_path",
        nargs="?",
        default=DEFAULT_DB_NAME,
        help=f"SQLite database path or name (defaults to Databanks/{DEFAULT_DB_NAME}).",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Directory to write sampled one-per-series DICOMs. Defaults to OnePerSeriesSamples/<input>_samples.",
    )
    parser.add_argument(
        "--max-file-mb",
        type=float,
        default=100.0,
        help="Maximum file size to consider during extraction and full parsing. Use 0 for no size limit.",
    )
    parser.add_argument(
        "--partial-read-mb",
        type=float,
        default=25.0,
        help="Maximum MB to read from oversized files during processing.",
    )
    parser.add_argument(
        "--no-partial-oversized",
        action="store_true",
        help="Disable capped header-only reads for oversized DICOM-like files during processing.",
    )
    parser.add_argument(
        "--no-subdirs",
        dest="process_subdirs",
        action="store_false",
        help="Treat the sampled output as a single scan instead of discovering subdirectories.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=None,
        help="Maximum number of workers for metadata extraction.",
    )
    parser.add_argument(
        "--skip-existing-paths",
        action="store_true",
        help="Skip files whose relative paths already exist in the database.",
    )
    parser.add_argument(
        "--no-auto-workers",
        action="store_true",
        help="Disable worker auto-tuning during processing.",
    )
    parser.add_argument(
        "--timing",
        action="store_true",
        help="Print processing timing details.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed processing output.",
    )

    args = parser.parse_args()
    if args.max_workers is not None and args.max_workers < 1:
        parser.error("--max-workers must be greater than zero")

    max_file_bytes = _parse_non_negative_mb(parser, args.max_file_mb, "--max-file-mb")
    partial_read_limit_bytes = _parse_positive_mb(parser, args.partial_read_mb, "--partial-read-mb")

    input_path = Path(args.input_path).expanduser().resolve()
    output_root = (args.output_root.expanduser().resolve() if args.output_root else _default_output_root(input_path))

    start_time = time.perf_counter()
    print(f"Input: {input_path}")
    print(f"Sample output: {output_root}")
    print(f"Databank: {args.db_path}")

    extract_progress = TerminalProgress("extract_one_per_series")
    extract_result = extract_one_per_series(
        input_path,
        output_root,
        max_file_bytes=max_file_bytes,
        progress_callback=extract_progress,
    )
    if extract_result["copied"] == 0:
        print("No sampled DICOM files were extracted; skipping processing.")
        extract_elapsed = time.perf_counter() - start_time
        print(f"Extract elapsed time: {extract_elapsed:.2f} seconds")
        print("Process elapsed time: 0.00 seconds")
        print(f"Total elapsed time (extract + process): {extract_elapsed:.2f} seconds")
        return

    extract_elapsed = time.perf_counter() - start_time
    print(f"Extracted {extract_result['copied']} sampled files. Starting metadata processing...")
    process_progress = TerminalProgress("process_dicom")
    process_start = time.perf_counter()
    process_directory(
        str(output_root),
        db_path=args.db_path,
        process_subdirs=args.process_subdirs,
        max_workers=args.max_workers,
        timing=args.timing,
        verbose=args.verbose,
        skip_existing_paths=args.skip_existing_paths,
        auto_workers=not args.no_auto_workers,
        max_file_bytes=max_file_bytes,
        partial_read_oversized=not args.no_partial_oversized,
        partial_read_limit_bytes=partial_read_limit_bytes,
        print_elapsed_summary=False,
        progress_callback=process_progress,
    )
    process_elapsed = time.perf_counter() - process_start
    total_elapsed = time.perf_counter() - start_time
    print(f"Extract elapsed time: {extract_elapsed:.2f} seconds")
    print(f"Process elapsed time: {process_elapsed:.2f} seconds")
    print(f"Total elapsed time (extract + process): {total_elapsed:.2f} seconds")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Copy one DICOM file per series directory while preserving the folder structure.
Series is inferred as the directory that directly contains DICOM files.
"""

import argparse
import os
import shutil
import time
from pathlib import Path
from typing import Optional

from dicom_browser.dicom_discovery import is_dicom_candidate
from dicom_browser.progress import ProgressCallback, ProgressTracker, TerminalProgress


def _copy_api_path(path: Path) -> str:
    """Return a path string suitable for Windows file copy APIs."""
    path_str = str(path)
    if os.name != "nt":
        return path_str
    if path_str.startswith("\\\\?\\"):
        return path_str
    if path_str.startswith("\\\\"):
        return "\\\\?\\UNC\\" + path_str.lstrip("\\")
    return "\\\\?\\" + path_str


def _count_directories(input_root: Path) -> int:
    total = 0
    for _dirpath, _dirnames, _filenames in os.walk(input_root):
        total += 1
    return total


def find_series_samples(input_root: Path, progress: Optional[ProgressTracker] = None):
    samples = []
    for index, (dirpath, _dirnames, filenames) in enumerate(os.walk(input_root), start=1):
        dicom_files = []
        for name in filenames:
            file_path = Path(dirpath) / name
            if is_dicom_candidate(file_path):
                dicom_files.append(name)
        if not dicom_files:
            if progress:
                progress.update(index, message=f"Found {len(samples)} series")
            continue
        dicom_files.sort()
        samples.append(Path(dirpath) / dicom_files[0])
        if progress:
            progress.update(index, message=f"Found {len(samples)} series")
    return samples


def copy_samples(
    samples,
    input_root: Path,
    output_root: Path,
    progress: Optional[ProgressTracker] = None,
    progress_offset: int = 0,
) -> int:
    copied = 0
    for file_path in samples:
        rel_dir = file_path.parent.relative_to(input_root)
        dest_dir = output_root / rel_dir
        os.makedirs(_copy_api_path(dest_dir), exist_ok=True)
        dest_path = dest_dir / file_path.name
        try:
            shutil.copy2(_copy_api_path(file_path), _copy_api_path(dest_path))
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                f"{exc}. Source: {file_path}. Destination: {dest_path}"
            ) from exc
        copied += 1
        if progress:
            progress.update(progress_offset + copied, message=f"Copied {copied} series samples")
    return copied


def extract_one_per_series(
    input_root: Path,
    output_root: Path,
    progress_callback: Optional[ProgressCallback] = None,
) -> dict:
    start_time = time.perf_counter()
    input_root = input_root.resolve()
    output_root = output_root.resolve()

    if not input_root.is_dir():
        raise ValueError(f"Input root is not a directory: {input_root}")

    dir_count = _count_directories(input_root)
    progress = ProgressTracker(
        total=dir_count,
        phase="Scanning",
        callback=progress_callback,
    )
    progress.emit()
    samples = find_series_samples(input_root, progress)

    if not samples:
        progress.finish("No DICOM files found")
        elapsed = time.perf_counter() - start_time
        return {
            "copied": 0,
            "series": 0,
            "output_root": str(output_root),
            "elapsed_s": elapsed,
        }

    progress.update(
        dir_count,
        total=dir_count + len(samples),
        phase="Copying",
        message=f"Found {len(samples)} series",
    )
    copied = copy_samples(samples, input_root, output_root, progress, progress_offset=dir_count)
    progress.finish(f"Copied {copied} series samples")

    elapsed = time.perf_counter() - start_time
    return {
        "copied": copied,
        "series": len(samples),
        "output_root": str(output_root),
        "elapsed_s": elapsed,
    }


def main() -> None:
    start_time = time.perf_counter()
    parser = argparse.ArgumentParser(
        description="Extract one DICOM file per series directory."
    )
    parser.add_argument("input_root", help="Root directory containing DICOM series")
    parser.add_argument("output_root", help="Directory to write the sampled DICOMs")
    args = parser.parse_args()

    input_root = Path(args.input_root).resolve()
    output_root = Path(args.output_root).resolve()

    if not input_root.is_dir():
        raise SystemExit(f"Input root is not a directory: {input_root}")

    terminal_progress = TerminalProgress("extract_one_per_series")
    result = extract_one_per_series(
        input_root,
        output_root,
        progress_callback=terminal_progress,
    )
    if result["copied"] == 0:
        print("No DICOM files found.")
        print(f"Elapsed time: {time.perf_counter() - start_time:.2f} seconds")
        return

    print(f"Copied {result['copied']} series samples into {output_root}")
    print(f"Elapsed time: {time.perf_counter() - start_time:.2f} seconds")


if __name__ == "__main__":
    main()

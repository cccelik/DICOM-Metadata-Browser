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

from dicom_browser.dicom_discovery import is_dicom_candidate


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


def find_series_samples(input_root: Path):
    samples = []
    for dirpath, _dirnames, filenames in os.walk(input_root):
        dicom_files = []
        for name in filenames:
            file_path = Path(dirpath) / name
            if is_dicom_candidate(file_path):
                dicom_files.append(name)
        if not dicom_files:
            continue
        dicom_files.sort()
        samples.append(Path(dirpath) / dicom_files[0])
    return samples


def copy_samples(samples, input_root: Path, output_root: Path) -> int:
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
    return copied


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

    samples = find_series_samples(input_root)
    if not samples:
        print("No DICOM files found.")
        print(f"Elapsed time: {time.perf_counter() - start_time:.2f} seconds")
        return

    copied = copy_samples(samples, input_root, output_root)
    print(f"Copied {copied} series samples into {output_root}")
    print(f"Elapsed time: {time.perf_counter() - start_time:.2f} seconds")


if __name__ == "__main__":
    main()

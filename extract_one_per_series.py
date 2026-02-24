#!/usr/bin/env python3
"""
Copy one DICOM file per series directory while preserving the folder structure.
Series is inferred as the directory that directly contains DICOM files.
"""

import argparse
import os
import shutil
from pathlib import Path

from dicom_discovery import is_dicom_candidate


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
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / file_path.name
        shutil.copy2(file_path, dest_path)
        copied += 1
    return copied


def main() -> None:
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
        return

    copied = copy_samples(samples, input_root, output_root)
    print(f"Copied {copied} series samples into {output_root}")


if __name__ == "__main__":
    main()

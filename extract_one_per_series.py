#!/usr/bin/env python3
"""
Copy one DICOM file per series directory while preserving the folder structure.
Series is inferred as the directory that directly contains DICOM files.
"""

import argparse
import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Optional

from dicom_browser.archive_utils import safe_archive_member_path
from dicom_browser.cli_paths import expand_path_patterns, safe_path_name
from dicom_browser.dicom_discovery import (
    DEFAULT_MAX_FILE_BYTES,
    has_private_bulk_data,
    is_dicom_candidate,
    max_file_mb_to_bytes,
)
from dicom_browser.progress import ProgressCallback, ProgressTracker, TerminalProgress

SUPPORTED_ARCHIVE_SUFFIXES = {".zip", ".7z"}


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


def _is_supported_archive(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_ARCHIVE_SUFFIXES


def _safe_extract_archive(
    archive_path: Path,
    output_dir: Path,
    progress: Optional[ProgressTracker] = None,
) -> None:
    output_dir = output_dir.resolve()
    if archive_path.suffix.lower() == ".zip":
        with zipfile.ZipFile(archive_path, "r") as archive:
            members = archive.infolist()
            if progress:
                progress.update(0, total=max(len(members), 1), phase="Extracting", message=f"Extracting {archive_path.name}")
            for index, member in enumerate(members, start=1):
                safe_archive_member_path(output_dir, member.filename)
                archive.extract(member, output_dir)
                if progress:
                    progress.update(index, message=f"Extracted {index}/{len(members)} archive entries")
        return
    if archive_path.suffix.lower() == ".7z":
        import py7zr  # type: ignore[import]
        with py7zr.SevenZipFile(archive_path, mode="r") as archive:
            for name in archive.getnames():
                safe_archive_member_path(output_dir, name)
            names = archive.getnames()
            if progress:
                progress.update(0, total=1, phase="Extracting", message=f"Extracting {len(names)} 7Z entries")
            archive.extractall(output_dir)
            if progress:
                progress.update(1, message=f"Extracted {len(names)} 7Z entries")
        for extracted_path in output_dir.rglob("*"):
            if extracted_path.is_file():
                try:
                    extracted_path.chmod(extracted_path.stat().st_mode | 0o600)
                except OSError:
                    pass
        return
    raise ValueError(f"Unsupported archive type: {archive_path.suffix}")


def find_series_samples(
    input_root: Path,
    progress: Optional[ProgressTracker] = None,
    max_file_bytes: Optional[int] = DEFAULT_MAX_FILE_BYTES,
):
    samples = []
    for index, (dirpath, _dirnames, filenames) in enumerate(os.walk(input_root), start=1):
        dicom_files = []
        for name in filenames:
            file_path = Path(dirpath) / name
            if is_dicom_candidate(file_path, max_file_bytes=max_file_bytes):
                dicom_files.append(file_path)
        if not dicom_files:
            if progress:
                progress.update(index, message=f"Found {len(samples)} series")
            continue
        dicom_files.sort(key=lambda path: path.name)
        preferred_files = [path for path in dicom_files if not has_private_bulk_data(path)]
        samples.append((preferred_files or dicom_files)[0])
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
    max_file_bytes: Optional[int] = DEFAULT_MAX_FILE_BYTES,
    progress_callback: Optional[ProgressCallback] = None,
) -> dict:
    start_time = time.perf_counter()
    input_root = input_root.expanduser().resolve()
    output_root = output_root.resolve()
    temp_extract_dir = None

    if _is_supported_archive(input_root):
        temp_extract_dir = tempfile.mkdtemp(prefix="one_per_series_")
        progress = ProgressTracker(
            total=1,
            phase="Extracting",
            callback=progress_callback,
        )
        progress.emit()
        try:
            _safe_extract_archive(input_root, Path(temp_extract_dir), progress)
        except Exception as exc:
            shutil.rmtree(temp_extract_dir, ignore_errors=True)
            raise ValueError(f"Could not extract archive: {exc}") from exc
        progress.update(progress.total, message=f"Extracted {input_root.name}")
        input_root = Path(temp_extract_dir).resolve()
    elif not input_root.is_dir():
        raise ValueError(f"Input root is not a directory, ZIP archive, or 7Z archive: {input_root}")

    try:
        dir_count = _count_directories(input_root)
        progress = ProgressTracker(
            total=dir_count,
            phase="Scanning",
            callback=progress_callback,
        )
        progress.emit()
        samples = find_series_samples(input_root, progress, max_file_bytes=max_file_bytes)

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
    finally:
        if temp_extract_dir:
            shutil.rmtree(temp_extract_dir, ignore_errors=True)

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
        description="Extract one DICOM file per series directory from a folder, ZIP archive, or 7Z archive."
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help=(
            "One or more input roots, archives, or wildcard patterns followed by the output directory. "
            "Example: extract_one_per_series.py \"USB1?\" samples"
        ),
    )
    parser.add_argument(
        "--max-file-mb",
        type=float,
        default=100.0,
        help="Maximum file size to consider in MB. Use 0 for no size limit.",
    )
    args = parser.parse_args()
    if args.max_file_mb < 0:
        parser.error("--max-file-mb must be zero or greater")
    if len(args.paths) < 2:
        parser.error("Provide at least one input path and an output directory")

    input_roots = expand_path_patterns(args.paths[:-1])
    output_root = Path(args.paths[-1]).expanduser().resolve()
    if not input_roots:
        parser.error("No input paths matched")

    total_copied = 0
    for index, input_root in enumerate(input_roots, start=1):
        if len(input_roots) > 1:
            print(f"\n=== Input {index}/{len(input_roots)}: {input_root} ===")
        if not input_root.is_dir() and not _is_supported_archive(input_root):
            raise SystemExit(f"Input root is not a directory, ZIP archive, or 7Z archive: {input_root}")

        target_root = output_root
        if len(input_roots) > 1:
            target_root = output_root / safe_path_name(input_root.stem if input_root.is_file() else input_root.name)

        terminal_progress = TerminalProgress("extract_one_per_series")
        result = extract_one_per_series(
            input_root,
            target_root,
            max_file_bytes=max_file_mb_to_bytes(args.max_file_mb),
            progress_callback=terminal_progress,
        )
        if result["copied"] == 0:
            print("No DICOM files found.")
            continue
        total_copied += result["copied"]
        print(f"Copied {result['copied']} series samples into {target_root}")

    if total_copied == 0:
        print("No DICOM files found.")
    print(f"Elapsed time: {time.perf_counter() - start_time:.2f} seconds")


if __name__ == "__main__":
    main()

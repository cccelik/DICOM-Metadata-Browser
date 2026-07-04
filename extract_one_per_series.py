#!/usr/bin/env python3
"""
Copy one DICOM file per series directory while preserving the folder structure.
Series is inferred as the directory that directly contains DICOM files.
"""

import argparse
import os
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Callable, Optional, TextIO

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
DebugCallback = Callable[[str], None]


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


def _build_diagnostic_callback(
    *,
    stream: Optional[TextIO] = None,
) -> Optional[DebugCallback]:
    if stream is None:
        return None

    def _debug(message: str) -> None:
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
        print(line, file=stream, flush=True)

    return _debug


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
    debug_callback: Optional[DebugCallback] = None,
    log_callback: Optional[DebugCallback] = None,
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
        if debug_callback:
            debug_callback(f"Directory {index}: {dirpath}")
        if log_callback:
            log_callback(f"Directory {index}: {dirpath} has {len(dicom_files)} DICOM candidate(s)")
        sample = dicom_files[0]
        for file_index, path in enumerate(dicom_files, start=1):
            if log_callback:
                log_callback(f"Checking private bulk data {file_index}/{len(dicom_files)}: {path}")
            check_start = time.perf_counter()
            has_bulk_data = has_private_bulk_data(path)
            if log_callback:
                elapsed = time.perf_counter() - check_start
                log_callback(
                    f"Private bulk data check finished in {elapsed:.3f}s "
                    f"({'private bulk data' if has_bulk_data else 'usable'}): {path}"
                )
            if not has_bulk_data:
                sample = path
                break
        if log_callback:
            log_callback(f"Selected sample: {sample}")
        samples.append(sample)
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
    debug_callback: Optional[DebugCallback] = None,
    log_callback: Optional[DebugCallback] = None,
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
        samples = find_series_samples(
            input_root,
            progress,
            max_file_bytes=max_file_bytes,
            debug_callback=debug_callback,
            log_callback=log_callback,
        )

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
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print the directory currently being scanned to stderr.",
    )
    parser.add_argument(
        "--log",
        type=Path,
        help="Write detailed per-directory and per-file diagnostic messages to this log file.",
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
    log_file = None
    try:
        if args.log:
            log_file = args.log.expanduser().open("a", encoding="utf-8")
        debug_callback = _build_diagnostic_callback(stream=sys.stderr if args.debug else None)
        log_callback = _build_diagnostic_callback(stream=log_file)
        if debug_callback:
            debug_callback("Starting extract_one_per_series directory debug")
        if log_callback:
            log_callback("Starting extract_one_per_series detailed diagnostics")
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
                debug_callback=debug_callback,
                log_callback=log_callback,
            )
            if result["copied"] == 0:
                print("No DICOM files found.")
                continue
            total_copied += result["copied"]
            print(f"Copied {result['copied']} series samples into {target_root}")
    finally:
        if log_file is not None:
            log_file.close()

    if total_copied == 0:
        print("No DICOM files found.")
    print(f"Elapsed time: {time.perf_counter() - start_time:.2f} seconds")


if __name__ == "__main__":
    main()

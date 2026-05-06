#!/usr/bin/env python3
"""
Process DICOM files and store metadata in database
Supports processing single directories or multiple scans in subdirectories
Also supports ZIP and 7Z archive files
"""

import argparse
import os
import shutil
import sqlite3
import tempfile
import time
import warnings
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dicom_browser.dicom_discovery import collect_dicom_files, is_dicom_candidate
from dicom_browser.extract_metadata import extract_metadata_from_paths
from dicom_browser.progress import ProgressCallback, ProgressTracker, TerminalProgress
from dicom_browser.qa_utils import (
    calculate_raw_injection_delay_minutes,
    compute_delay_minutes as shared_compute_delay_minutes,
    compute_dose_per_kg as shared_compute_dose_per_kg,
    parse_db_float as shared_parse_db_float,
    parse_time_to_24hour as shared_parse_time_to_24hour,
    select_study_representatives,
)
from dicom_browser.store_metadata import init_database

warnings.filterwarnings(
    "ignore",
    message="Invalid value for VR UI"
)

BASE_DIR = Path(__file__).resolve().parent
DATABANK_DIR = BASE_DIR / "Databanks"
DEFAULT_DB_NAME = "dicom_metadata.db"

def _parse_db_float(value: Optional[object]) -> Optional[float]:
    return shared_parse_db_float(value)


def _parse_time_to_24hour(time_str: Optional[object]):
    return shared_parse_time_to_24hour(time_str)


def _calculate_injection_delay(injection_date, injection_time, acquisition_date, acquisition_time):
    return calculate_raw_injection_delay_minutes(
        injection_date,
        injection_time,
        acquisition_date,
        acquisition_time,
    )


def _compute_delay_minutes(row: dict) -> Optional[float]:
    return shared_compute_delay_minutes(row)


def _compute_dose_per_kg(row: dict) -> Optional[float]:
    return shared_compute_dose_per_kg(row)


def _select_representative_series(rows: List[dict]) -> List[str]:
    representatives = select_study_representatives(rows)
    return [
        entry["row"]["series_instance_uid"]
        for entry in representatives.values()
        if entry["row"].get("series_instance_uid")
    ]


def prune_non_representative_series(conn: sqlite3.Connection) -> int:
    cursor = conn.execute("""
        WITH study_weights AS (
            SELECT study_instance_uid, MAX(patient_weight) AS study_patient_weight
            FROM dicom_metadata
            GROUP BY study_instance_uid
        )
        SELECT m.series_instance_uid,
               m.study_instance_uid,
               m.modality,
               m.injected_activity,
               m.patient_weight,
               m.injection_date,
               m.injection_time,
               m.acquisition_date,
               m.acquisition_time,
               m.study_date,
               w.study_patient_weight
        FROM dicom_metadata m
        LEFT JOIN study_weights w ON m.study_instance_uid = w.study_instance_uid
    """)
    columns = [col[0] for col in cursor.description]
    rows = [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]
    if not rows:
        return 0
    keep_series = _select_representative_series(rows)
    if not keep_series:
        return 0

    conn.execute("UPDATE dicom_metadata SET is_representative = 0")
    chunk_size = 900
    for i in range(0, len(keep_series), chunk_size):
        chunk = keep_series[i:i + chunk_size]
        placeholders = ",".join("?" for _ in chunk)
        conn.execute(
            f"UPDATE dicom_metadata SET is_representative = 1 WHERE series_instance_uid IN ({placeholders})",
            chunk,
        )
    cursor = conn.execute("SELECT COUNT(*) FROM dicom_metadata WHERE is_representative = 0")
    return cursor.fetchone()[0]


def _bulk_insert_metadata(
    conn: sqlite3.Connection,
    metadata_entries: List[Tuple[Path, object]],
    rel_base: Path,
    scan_root: str,
    batch_size: int = 500,
    progress_total: Optional[int] = None,
    vprint=None,
    progress_callback: Optional[ProgressCallback] = None,
) -> Tuple[int, int, int]:
    from dicom_browser.store_metadata import insert_metadata

    processed = 0
    skipped_duplicates = 0
    skipped_invalid = 0
    batch_metadata = []
    batch_paths = []

    def _flush() -> None:
        nonlocal processed, skipped_duplicates, skipped_invalid
        for meta_item, file_path_str in zip(batch_metadata, batch_paths, strict=False):
            inserted, reason = insert_metadata(
                conn,
                meta_item,
                file_path_str,
                scan_root=scan_root,
                skip_existing=True,
                commit=False,
            )
            if inserted:
                processed += 1
                if vprint and progress_total and processed % 10 == 0:
                    vprint(f"   ✓ Processed {processed}/{progress_total} files...")
            elif reason in ("series_exists", "already_exists"):
                skipped_duplicates += 1
            else:
                skipped_invalid += 1
            if progress_callback:
                progress_callback({})
        conn.commit()
        batch_metadata.clear()
        batch_paths.clear()

    for file_path, meta in metadata_entries:
        batch_metadata.append(meta)
        batch_paths.append(str(file_path.relative_to(rel_base)))
        if len(batch_metadata) >= batch_size:
            _flush()

    if batch_metadata:
        _flush()

    return processed, skipped_duplicates, skipped_invalid


def _filter_existing_paths(
    file_paths: List[Path],
    base_dir: Path,
    existing_paths: Optional[set],
) -> Tuple[List[Path], int]:
    if not existing_paths:
        return file_paths, 0

    filtered_files: List[Path] = []
    skipped_existing = 0
    for file_path in file_paths:
        rel_path = str(file_path.relative_to(base_dir))
        if rel_path in existing_paths:
            skipped_existing += 1
            continue
        filtered_files.append(file_path)
    return filtered_files, skipped_existing


def _extract_and_store(
    conn: sqlite3.Connection,
    dcm_files: List[Path],
    rel_base: Path,
    scan_root: str,
    max_workers: Optional[int],
    progress_total: Optional[int] = None,
    vprint=None,
    progress_callback: Optional[ProgressCallback] = None,
) -> Tuple[int, int, int, List[Tuple[Path, object]], Dict[str, float]]:
    timings: Dict[str, float] = {}

    t_extract = time.perf_counter()
    metadata_entries = extract_metadata_from_paths(
        dcm_files,
        max_workers=max_workers,
        progress_callback=lambda _path, _meta: progress_callback({}) if progress_callback else None,
    )
    timings["extract_metadata_s"] = time.perf_counter() - t_extract
    skipped_invalid = len(dcm_files) - len(metadata_entries)

    t_insert = time.perf_counter()
    processed, skipped_dup_insert, skipped_invalid_insert = _bulk_insert_metadata(
        conn,
        metadata_entries,
        rel_base,
        scan_root,
        progress_total=progress_total,
        vprint=vprint,
        progress_callback=progress_callback,
    )
    timings["insert_metadata_s"] = time.perf_counter() - t_insert
    skipped_invalid += skipped_invalid_insert

    return processed, skipped_dup_insert, skipped_invalid, metadata_entries, timings


def process_single_scan(
    scan_dir: Path,
    conn,
    base_dir: Path,
    max_workers: Optional[int] = None,
    existing_paths: Optional[set] = None,
    scan_root_label: Optional[str] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> Tuple[int, int, int, List[str], Dict[str, float]]:
    """Process a single scan directory and store its metadata in the database."""
    from dicom_browser.store_metadata import study_exists
    scan_root = scan_root_label or str(base_dir.resolve())
    timings: Dict[str, float] = {}
    t0 = time.perf_counter()

    dcm_files = collect_dicom_files(scan_dir, recursive=True)
    dcm_files, skipped_existing = _filter_existing_paths(
        dcm_files,
        base_dir,
        existing_paths,
    )

    if not dcm_files:
        return 0, 0, 0, [], timings

    timings["scan_dicom_files_s"] = time.perf_counter() - t0

    processed, skipped_dup_insert, skipped_invalid, metadata_entries, extract_insert_timings = _extract_and_store(
        conn,
        dcm_files,
        base_dir,
        scan_root,
        max_workers=max_workers,
        progress_total=None,
        vprint=None,
        progress_callback=progress_callback,
    )
    timings.update(extract_insert_timings)

    new_studies = set()
    seen_studies = set()
    for _, meta in metadata_entries:
        if meta.study_instance_uid and meta.study_instance_uid not in seen_studies:
            seen_studies.add(meta.study_instance_uid)
            if not study_exists(conn, meta.study_instance_uid):
                new_studies.add(meta.study_instance_uid)

    return (
        processed,
        skipped_dup_insert + skipped_existing,
        skipped_invalid,
        list(new_studies),
        timings,
    )


def process_directory(
    dicom_dir: str,
    db_path: str = DEFAULT_DB_NAME,
    process_subdirs: bool = True,
    max_workers: Optional[int] = None,
    timing: bool = False,
    verbose: bool = False,
    skip_existing_paths: bool = False,
    auto_workers: bool = True,
    scan_root_label: Optional[str] = None,
    progress_callback: Optional[ProgressCallback] = None,
):
    """Process all DICOM files in a directory, ZIP, or 7Z file and store metadata.

    Args:
        dicom_dir: Directory containing DICOM files, subdirectories with scans, or a ZIP/7Z archive file
        db_path: Path to SQLite database file
        process_subdirs: If True, automatically process subdirectories as separate scans
        max_workers: Maximum number of workers to use for metadata extraction
        timing: Print timing information after processing
        skip_existing_paths: If True, skip files whose relative paths already exist in the database
        auto_workers: If True, benchmark a small sample to pick worker count
    """
    dicom_path = Path(dicom_dir)
    start_time = time.perf_counter()

    DATABANK_DIR.mkdir(parents=True, exist_ok=True)
    db_path_obj = Path(db_path)
    if not db_path_obj.is_absolute():
        db_path = str(DATABANK_DIR / db_path_obj.name)
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    def _print_timing(extra_timings: Optional[Dict[str, float]] = None):
        nonlocal start_time
        if start_time is None:
            return
        elapsed = time.perf_counter() - start_time
        print(f"Elapsed time: {elapsed:.2f}s")
        if timing and extra_timings:
            for label, seconds in extra_timings.items():
                print(f"{label}: {seconds:.2f}s")
        start_time = None

    def _vprint(message: str = "") -> None:
        if verbose:
            print(message)

    def _sample_dicom_files(sample_root: Path, limit: int = 200) -> List[Path]:
        return collect_dicom_files(sample_root, recursive=True, limit=limit)

    def _auto_tune_workers(sample_paths: List[Path]) -> Optional[int]:
        if not sample_paths:
            return None
        cpu_count = os.cpu_count() or 4
        max_cap = min(cpu_count, 32, len(sample_paths))
        candidates = [w for w in (1, 2, 4, 8, 16, 32) if w <= max_cap]
        if max_cap not in candidates:
            candidates.append(max_cap)
        candidates = sorted(set(candidates))
        best_workers = candidates[0]
        best_time = float("inf")
        _vprint(f"   Auto-tuning workers using {len(sample_paths)} sample files...")
        for workers in candidates:
            t0 = time.perf_counter()
            extract_metadata_from_paths(
                sample_paths,
                max_workers=workers,
            )
            elapsed = time.perf_counter() - t0
            _vprint(f"   - {workers} workers: {elapsed:.2f}s")
            if elapsed < best_time:
                best_time = elapsed
                best_workers = workers
        _vprint(f"   Auto-tune selected {best_workers} workers")
        return best_workers

    if not dicom_path.exists():
        _vprint(f"Error: Path {dicom_dir} does not exist")
        return

    print(f"Starting processing: {dicom_path}")

    # Check if input is a ZIP or 7Z file
    temp_extract_dir = None
    extract_timings: Dict[str, float] = {}
    if dicom_path.is_file():
        filename_lower = dicom_path.name.lower()
        if filename_lower.endswith('.zip') or filename_lower.endswith('.7z'):
            _vprint(f"📦 Detected archive file: {dicom_path.name}")
            _vprint("   Extracting to temporary directory...")

            # Create temporary directory for extraction
            temp_extract_dir = tempfile.mkdtemp(prefix='dicom_process_')
            extract_dir = Path(temp_extract_dir)

            try:
                t_archive = time.perf_counter()
                if filename_lower.endswith('.zip'):
                    # Extract ZIP file
                    with zipfile.ZipFile(dicom_path, 'r') as zip_ref:
                        zip_ref.extractall(extract_dir)
                    _vprint("   ✓ Extracted ZIP file")
                elif filename_lower.endswith('.7z'):
                    # Extract 7Z file
                    try:
                        import py7zr  # type: ignore[import]
                        with py7zr.SevenZipFile(dicom_path, mode='r') as archive:
                            archive.extractall(extract_dir)
                        _vprint("   ✓ Extracted 7Z file")
                    except ImportError:
                        # Fallback to system 7z command
                        import subprocess
                        result = subprocess.run(
                            ['7z', 'x', str(dicom_path), '-o' + str(extract_dir), '-y'],
                            capture_output=True,
                            text=True
                        )
                        if result.returncode != 0:
                            _vprint("   ✗ Error: Failed to extract 7Z file")
                            _vprint("   Install py7zr: pip install py7zr")
                            _vprint("   Or ensure system 7z command is available")
                            try:
                                shutil.rmtree(temp_extract_dir)
                            except OSError:
                                pass
                            _print_timing()
                            return
                        _vprint("   ✓ Extracted 7Z file (using system 7z)")
                extract_timings["archive_extract_s"] = time.perf_counter() - t_archive

                # Update path to extracted directory
                dicom_path = extract_dir
                _vprint()
            except (OSError, ValueError, zipfile.BadZipFile) as e:
                _vprint(f"   ✗ Error extracting archive: {e}")
                try:
                    shutil.rmtree(temp_extract_dir)
                except OSError:
                    pass
                return

    # Now process as a directory (original logic continues)

    # Initialize database
    conn = init_database(db_path)

    if auto_workers and max_workers is None:
        sample_paths = _sample_dicom_files(dicom_path)
        tuned_workers = _auto_tune_workers(sample_paths)
        if tuned_workers:
            max_workers = tuned_workers

    existing_paths = None
    if skip_existing_paths:
        rows = conn.execute("SELECT file_path FROM dicom_metadata").fetchall()
        existing_paths = {row[0] for row in rows}

    progress_tracker: Optional[ProgressTracker] = None
    progress_file_units = 0
    if progress_callback:
        if dicom_path.is_file():
            candidate_files = [dicom_path] if is_dicom_candidate(dicom_path) else []
            progress_base = dicom_path.parent
        else:
            candidate_files = collect_dicom_files(dicom_path, recursive=True)
            progress_base = dicom_path
        candidate_files, _progress_skipped_existing = _filter_existing_paths(
            candidate_files,
            progress_base,
            existing_paths,
        )
        progress_file_units = len(candidate_files) * 2
        progress_tracker = ProgressTracker(
            total=progress_file_units + 1,
            phase="Processing",
            callback=progress_callback,
        )
        progress_tracker.emit()

    def _advance_progress(_event: dict) -> None:
        if progress_tracker:
            progress_tracker.update(advance=1)

    def _finish_progress(message: str) -> None:
        if progress_tracker:
            progress_tracker.finish(message)

    if dicom_path.is_file():
        _vprint(f"📄 Processing single file: {dicom_path.name}")
        dcm_files = [dicom_path] if is_dicom_candidate(dicom_path) else []
        scan_root = scan_root_label or str(dicom_path.parent.resolve())

        if existing_paths:
            rel_path = dicom_path.name
            if rel_path in existing_paths:
                dcm_files = []
                skipped_existing = 1
            else:
                skipped_existing = 0
        else:
            skipped_existing = 0

        if not dcm_files:
            _vprint("   ⚠️  No DICOM files found")
            conn.close()
            if temp_extract_dir:
                try:
                    shutil.rmtree(temp_extract_dir)
                    _vprint("   Cleaned up temporary extraction directory")
                except OSError:
                    pass
            _finish_progress("No DICOM files found")
            _print_timing()
            return

        processed, skipped_dup_insert, skipped_invalid, _metadata_entries, run_timings = _extract_and_store(
            conn,
            dcm_files,
            dicom_path.parent,
            scan_root,
            max_workers=max_workers,
            progress_total=len(dcm_files),
            vprint=_vprint,
            progress_callback=_advance_progress,
        )
        extract_timings.update(run_timings)
        skipped_duplicates = skipped_existing + skipped_dup_insert

        if skipped_duplicates > 0:
            _vprint(f"   ⚠️  Skipped {skipped_duplicates} duplicate files")
        if skipped_invalid > 0:
            _vprint(f"   ⚠️  Skipped {skipped_invalid} invalid files")

        _vprint(f"   ✅ Added {processed} new files to database")
    elif dicom_path.is_dir():
        # Check if directory contains subdirectories (works with any directory names)
        subdirs = [d for d in dicom_path.iterdir() if d.is_dir() and not d.name.startswith('.')]

        # Decide whether to process subdirectories or files directly
        if process_subdirs and subdirs:
            # Check if subdirectories contain DICOM files (generic check - works with any directory names)
            has_dicom_in_subdirs = False
            for subdir in subdirs:
                if collect_dicom_files(subdir, recursive=True, limit=1):
                    has_dicom_in_subdirs = True
                    break

            if has_dicom_in_subdirs:
                # Process each subdirectory as a separate scan
                _vprint(f"📂 Processing multiple scans in: {dicom_path}")
                _vprint(f"   Found {len(subdirs)} subdirectories\n")

                total_processed = 0
                total_skipped_duplicates = 0
                total_skipped_invalid = 0
                total_existing_studies = 0

                # First, check if there are DICOM files directly in the root directory
                root_dcm_files = collect_dicom_files(dicom_path, recursive=False)

                if root_dcm_files:
                    _vprint(f"   [0/{len(subdirs)+1}] Processing root directory files ({len(root_dcm_files)} file(s))")
                    processed, skipped_dup, skipped_inv, new_studies, scan_timings = process_single_scan(
                        dicom_path,
                        conn,
                        dicom_path,
                        max_workers=max_workers,
                        existing_paths=existing_paths,
                        scan_root_label=scan_root_label,
                        progress_callback=_advance_progress,
                    )
                    if timing and scan_timings:
                        _vprint("      ⏱️ scan timings:")
                        for label, seconds in scan_timings.items():
                            _vprint(f"         - {label}: {seconds:.2f}s")
                    total_processed += processed
                    total_skipped_duplicates += skipped_dup
                    total_skipped_invalid += skipped_inv

                    status_parts = []
                    if processed > 0:
                        if new_studies:
                            status_parts.append(f"Added {processed} new files ({len(new_studies)} new study/studies)")
                        else:
                            status_parts.append(f"Added {processed} new series to existing study/studies")

                    if skipped_dup > 0:
                        if processed == 0:
                            status_parts.append(f"All series already exist, skipped {skipped_dup} files")
                        else:
                            status_parts.append(f"Skipped {skipped_dup} duplicate series")

                    if skipped_inv > 0:
                        status_parts.append(f"Skipped {skipped_inv} invalid files")

                    if status_parts:
                        _vprint(f"      ✓ {' | '.join(status_parts)}")
                    else:
                        _vprint(f"      ✓ Processed {processed} files")
                    _vprint()  # Blank line before subdirectories

                # Process each subdirectory as a separate scan
                for idx, scan_dir in enumerate(subdirs, 1):
                    offset = 1 if root_dcm_files else 0
                    _vprint(f"   [{idx+offset}/{len(subdirs)+offset}] Processing: {scan_dir.name}")
                    processed, skipped_dup, skipped_inv, new_studies, scan_timings = process_single_scan(
                        scan_dir,
                        conn,
                        dicom_path,
                        max_workers=max_workers,
                        existing_paths=existing_paths,
                        scan_root_label=scan_root_label,
                        progress_callback=_advance_progress,
                    )
                    if timing and scan_timings:
                        _vprint("      ⏱️ scan timings:")
                        for label, seconds in scan_timings.items():
                            _vprint(f"         - {label}: {seconds:.2f}s")
                    total_processed += processed
                    total_skipped_duplicates += skipped_dup
                    total_skipped_invalid += skipped_inv

                    # Build status message
                    status_parts = []
                    if processed > 0:
                        if new_studies:
                            status_parts.append(f"Added {processed} new files ({len(new_studies)} new study/studies)")
                        else:
                            status_parts.append(f"Added {processed} new series to existing study/studies")

                    if skipped_dup > 0:
                        if processed == 0:
                            status_parts.append(f"All series already exist, skipped {skipped_dup} files")
                        else:
                            status_parts.append(f"Skipped {skipped_dup} duplicate series")

                    if skipped_inv > 0:
                        status_parts.append(f"Skipped {skipped_inv} invalid files")

                    if status_parts:
                        _vprint(f"      ✓ {' | '.join(status_parts)}")
                    else:
                        _vprint(f"      ✓ Processed {processed} files")

                    # Track existing studies for summary
                    if processed == 0 and skipped_dup > 0:
                        total_existing_studies += 1

                _vprint("\n   ✅ Summary:")
                _vprint(f"      • New files added: {total_processed}")
                if total_skipped_duplicates > 0:
                    _vprint(f"      • Duplicate files skipped: {total_skipped_duplicates}")
                if total_skipped_invalid > 0:
                    _vprint(f"      • Invalid files skipped: {total_skipped_invalid}")
                if total_existing_studies > 0:
                    _vprint(f"      • Scans already in database: {total_existing_studies}")
            else:
                # Process files directly (recursive)
                _vprint(f"📂 Processing DICOM files in: {dicom_path} (recursive)")
                dcm_files = collect_dicom_files(dicom_path, recursive=True)
                scan_root = scan_root_label or str(dicom_path.resolve())

                dcm_files, skipped_existing = _filter_existing_paths(
                    dcm_files,
                    dicom_path,
                    existing_paths,
                )

                if not dcm_files:
                    _vprint("   ⚠️  No DICOM files found")
                    conn.close()
                    _finish_progress("No DICOM files found")
                    _print_timing()
                    return

                _vprint(f"   📄 Found {len(dcm_files)} DICOM files")

                processed, skipped_dup_insert, skipped_invalid, _metadata_entries, run_timings = _extract_and_store(
                    conn,
                    dcm_files,
                    dicom_path,
                    scan_root,
                    max_workers=max_workers,
                    progress_total=len(dcm_files),
                    vprint=_vprint,
                    progress_callback=_advance_progress,
                )
                extract_timings.update(run_timings)
                skipped_duplicates = skipped_existing + skipped_dup_insert

                if skipped_duplicates > 0:
                    _vprint(f"   ⚠️  Skipped {skipped_duplicates} duplicate files")
                if skipped_invalid > 0:
                    _vprint(f"   ⚠️  Skipped {skipped_invalid} invalid files")

                _vprint(f"   ✅ Added {processed} new files to database")
        else:
            # Process files directly (single directory or no subdirs)
            _vprint(f"📂 Processing DICOM files in: {dicom_path}")
            dcm_files = collect_dicom_files(dicom_path, recursive=True)
            scan_root = scan_root_label or str(dicom_path.resolve())

            dcm_files, skipped_existing = _filter_existing_paths(
                dcm_files,
                dicom_path,
                existing_paths,
            )

            if not dcm_files:
                _vprint("   ⚠️  No DICOM files found")
                conn.close()
                if temp_extract_dir:
                    try:
                        shutil.rmtree(temp_extract_dir)
                        _vprint("   Cleaned up temporary extraction directory")
                    except OSError:
                        pass
                _finish_progress("No DICOM files found")
                _print_timing()
                return

            _vprint(f"   📄 Found {len(dcm_files)} DICOM files")

            processed, skipped_dup_insert, skipped_invalid, _metadata_entries, run_timings = _extract_and_store(
                conn,
                dcm_files,
                dicom_path,
                scan_root,
                max_workers=max_workers,
                progress_total=len(dcm_files),
                vprint=_vprint,
                progress_callback=_advance_progress,
            )
            extract_timings.update(run_timings)
            skipped_duplicates = skipped_existing + skipped_dup_insert

            if skipped_duplicates > 0:
                _vprint(f"   ⚠️  Skipped {skipped_duplicates} duplicate files")
            if skipped_invalid > 0:
                _vprint(f"   ⚠️  Skipped {skipped_invalid} invalid files")

            _vprint(f"   ✅ Added {processed} new files to database")
    else:
        _vprint("Error: Input path must be a directory, archive, or DICOM file")
        conn.close()
        _finish_progress("Input path is invalid")
        _print_timing()
        return

    _vprint("\n   🧹 Marking representative series...")
    if progress_tracker:
        progress_tracker.update(
            progress_file_units,
            phase="Finalizing",
            message="Marking representative series",
        )
    try:
        pruned = prune_non_representative_series(conn)
        conn.commit()
        if progress_tracker:
            progress_tracker.update(
                progress_tracker.total,
                phase="Finalizing",
                message=f"Marked {pruned} non-representative series",
            )
        _vprint(f"   ✓ Marked {pruned} non-representative series")
    except sqlite3.Error as e:
        if progress_tracker:
            progress_tracker.update(
                progress_tracker.total,
                phase="Finalizing",
                message=f"Representative-series step skipped: {e}",
            )
        _vprint(f"   ⚠ Warning: Could not mark representative series: {e}")

    conn.close()
    _vprint(f"\n   💾 Database saved to: {db_path}")

    # Clean up temporary directory if it was created from archive extraction
    if temp_extract_dir:
        try:
            _vprint("   Cleaning up temporary extraction directory...")
            shutil.rmtree(temp_extract_dir)
            _vprint("   ✓ Cleaned up")
        except OSError as e:
            _vprint(f"   ⚠ Warning: Could not clean up temp directory: {e}")

    if progress_tracker:
        progress_tracker.finish("Processing complete")
    print("Processing ended")
    _print_timing(extract_timings)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Process DICOM files and store metadata in a SQLite database."
    )
    parser.add_argument(
        "dicom_dir",
        help="Directory or archive that contains DICOM files.",
    )
    parser.add_argument(
        "db_path",
        nargs="?",
        default=DEFAULT_DB_NAME,
        help=f"SQLite database path or name (defaults to Databanks/{DEFAULT_DB_NAME}).",
    )
    parser.add_argument(
        "--no-subdirs",
        dest="process_subdirs",
        action="store_false",
        help="Treat the entire input as a single scan instead of discovering subdirectories.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=None,
        help="Maximum number of workers for metadata extraction (defaults to min(32, file count)).",
    )
    parser.add_argument(
        "--timing",
        action="store_true",
        help="Print elapsed time after processing completes.",
    )
    parser.add_argument(
        "--skip-existing-paths",
        action="store_true",
        help="Skip files whose relative paths already exist in the database.",
    )
    parser.add_argument(
        "--no-auto-workers",
        action="store_true",
        help="Disable auto-tuning worker count.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed processing output.",
    )

    args = parser.parse_args()

    if args.max_workers is not None and args.max_workers < 1:
        parser.error("--max-workers must be greater than zero")

    terminal_progress = TerminalProgress("process_dicom")
    process_directory(
        args.dicom_dir,
        db_path=args.db_path,
        process_subdirs=args.process_subdirs,
        max_workers=args.max_workers,
        timing=args.timing,
        verbose=args.verbose,
        skip_existing_paths=args.skip_existing_paths,
        auto_workers=not args.no_auto_workers,
        progress_callback=terminal_progress,
    )

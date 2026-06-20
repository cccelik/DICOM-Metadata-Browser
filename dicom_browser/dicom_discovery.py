import zipfile
from pathlib import Path
from typing import Dict, List, Optional

import pydicom
from pydicom.errors import InvalidDicomError
from pydicom.filereader import read_partial
from pydicom.tag import BaseTag, Tag

from .progress import ProgressCallback, ProgressTracker

KNOWN_DICOM_EXTENSIONS = {".dcm", ".ima"}
IGNORED_FILENAMES = {".ds_store"}
ARCHIVE_EXTENSIONS = {".zip", ".7z"}
DEFAULT_MAX_FILE_BYTES = 100 * 1024 * 1024
DEFAULT_PRIVATE_BULK_DATA_BYTES = 8 * 1024 * 1024
PRIVATE_BULK_DATA_VRS = {"OB", "OD", "OF", "OL", "OV", "OW", "UN"}
UNDEFINED_LENGTH = 0xFFFFFFFF


def max_file_mb_to_bytes(value: Optional[float]) -> Optional[int]:
    if value is None or value <= 0:
        return None
    return int(value * 1024 * 1024)


def format_bytes(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024


def is_metadata_artifact(path: Path) -> bool:
    name_lower = path.name.lower()
    if name_lower in IGNORED_FILENAMES:
        return True
    if path.name.startswith("._"):
        return True
    return "__MACOSX" in path.parts


def has_dicom_signature(path: Path) -> bool:
    try:
        if path.stat().st_size < 132:
            return False
        with path.open("rb") as fh:
            fh.seek(128)
            return fh.read(4) == b"DICM"
    except (OSError, PermissionError):
        return False


def is_over_size_limit(path: Path, max_file_bytes: Optional[int]) -> bool:
    if not max_file_bytes:
        return False
    try:
        return path.stat().st_size > max_file_bytes
    except (OSError, PermissionError):
        return False


def can_parse_as_dicom(path: Path) -> bool:
    try:
        pydicom.dcmread(path, stop_before_pixels=True, force=False)
        return True
    except (InvalidDicomError, OSError, PermissionError, ValueError):
        return False


def is_private_bulk_data_boundary(
    tag: BaseTag | int | tuple[int, int],
    vr: Optional[str],
    length: Optional[int],
    large_binary_threshold: int = DEFAULT_PRIVATE_BULK_DATA_BYTES,
) -> bool:
    """Return True for private/vendor raw payload elements, not normal Pixel Data."""
    element_tag = Tag(tag)
    if element_tag.group >= 0x7FE1:
        return True
    if not element_tag.is_private or vr not in PRIVATE_BULK_DATA_VRS:
        return False
    if length in (None, UNDEFINED_LENGTH):
        return True
    return length >= large_binary_threshold


def has_private_bulk_data(path: Path) -> bool:
    """Detect DICOM files whose first bulk payload is private/vendor raw data."""
    found_private_bulk = False

    def _stop_when(tag: BaseTag, vr: Optional[str], length: int) -> bool:
        nonlocal found_private_bulk
        if is_private_bulk_data_boundary(tag, vr, length):
            found_private_bulk = True
            return True
        return Tag(tag).group == 0x7FE0

    try:
        with path.open("rb") as fh:
            read_partial(fh, stop_when=_stop_when, force=False)
    except (EOFError, InvalidDicomError, OSError, PermissionError, ValueError):
        return False
    return found_private_bulk


def is_dicom_candidate(
    path: Path,
    max_file_bytes: Optional[int] = DEFAULT_MAX_FILE_BYTES,
    include_oversized: bool = False,
) -> bool:
    if not path.is_file() or path.is_symlink() or is_metadata_artifact(path):
        return False
    oversized = is_over_size_limit(path, max_file_bytes)
    if oversized and not include_oversized:
        return False

    suffix = path.suffix.lower()
    if suffix in KNOWN_DICOM_EXTENSIONS:
        return True
    if has_dicom_signature(path):
        return True
    if oversized:
        return False
    if not suffix:
        return can_parse_as_dicom(path)
    return False


def collect_dicom_files(
    root: Path,
    recursive: bool = True,
    limit: Optional[int] = None,
    max_file_bytes: Optional[int] = DEFAULT_MAX_FILE_BYTES,
    include_oversized: bool = False,
) -> List[Path]:
    if not root.is_dir():
        return []

    matched: List[Path] = []
    iterator = root.rglob("*") if recursive else root.iterdir()
    for file_path in iterator:
        if not is_dicom_candidate(
            file_path,
            max_file_bytes=max_file_bytes,
            include_oversized=include_oversized,
        ):
            continue
        matched.append(file_path)
        if limit is not None and len(matched) >= limit:
            break
    return matched


def analyze_input_size(
    root: Path,
    recursive: bool = True,
    max_file_bytes: Optional[int] = DEFAULT_MAX_FILE_BYTES,
    largest_limit: int = 10,
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict[str, object]:
    listing_progress = ProgressTracker(total=0, phase="Listing", callback=progress_callback)
    listing_progress.emit()
    if root.is_file():
        files = [root]
    elif root.is_dir():
        iterator = root.rglob("*") if recursive else root.iterdir()
        files = [path for path in iterator if path.is_file() and not path.is_symlink()]
    else:
        return {"exists": False, "message": "Input path does not exist."}

    summary: Dict[str, object] = {
        "exists": True,
        "path": str(root),
        "threshold_bytes": max_file_bytes,
        "threshold": format_bytes(max_file_bytes) if max_file_bytes else "Unlimited",
        "total_files": 0,
        "total_bytes": 0,
        "candidate_files": 0,
        "candidate_bytes": 0,
        "oversized_dicom_like_files": 0,
        "oversized_dicom_like_bytes": 0,
        "oversized_other_files": 0,
        "oversized_other_bytes": 0,
        "non_dicom_files": 0,
        "non_dicom_bytes": 0,
        "artifact_files": 0,
        "artifact_bytes": 0,
        "archive_files": 0,
        "archive_bytes": 0,
        "extensions": {},
        "largest_oversized": [],
    }
    largest: List[Dict[str, object]] = []
    extensions: Dict[str, Dict[str, object]] = {}
    progress = ProgressTracker(total=len(files), phase="Analyzing", callback=progress_callback)
    progress.emit()

    for index, path in enumerate(files, start=1):
        try:
            size = path.stat().st_size
        except (OSError, PermissionError):
            progress.update(index, message=f"Analyzed {index}/{len(files)} files")
            continue
        suffix = path.suffix.lower() or "[none]"
        ext_stats = extensions.setdefault(suffix, {"files": 0, "bytes": 0})
        ext_stats["files"] = int(ext_stats["files"]) + 1
        ext_stats["bytes"] = int(ext_stats["bytes"]) + size

        summary["total_files"] = int(summary["total_files"]) + 1
        summary["total_bytes"] = int(summary["total_bytes"]) + size

        if is_metadata_artifact(path):
            summary["artifact_files"] = int(summary["artifact_files"]) + 1
            summary["artifact_bytes"] = int(summary["artifact_bytes"]) + size
            progress.update(index, message=f"Analyzed {index}/{len(files)} files")
            continue
        if suffix in ARCHIVE_EXTENSIONS:
            summary["archive_files"] = int(summary["archive_files"]) + 1
            summary["archive_bytes"] = int(summary["archive_bytes"]) + size
            progress.update(index, message=f"Analyzed {index}/{len(files)} files")
            continue

        oversized = bool(max_file_bytes and size > max_file_bytes)
        dicom_like = suffix in KNOWN_DICOM_EXTENSIONS or has_dicom_signature(path)
        if oversized:
            item = {"path": str(path), "size_bytes": size, "size": format_bytes(size), "dicom_like": dicom_like}
            largest.append(item)
            largest.sort(key=lambda entry: int(entry["size_bytes"]), reverse=True)
            del largest[largest_limit:]
            if dicom_like:
                summary["oversized_dicom_like_files"] = int(summary["oversized_dicom_like_files"]) + 1
                summary["oversized_dicom_like_bytes"] = int(summary["oversized_dicom_like_bytes"]) + size
            else:
                summary["oversized_other_files"] = int(summary["oversized_other_files"]) + 1
                summary["oversized_other_bytes"] = int(summary["oversized_other_bytes"]) + size
            progress.update(index, message=f"Analyzed {index}/{len(files)} files")
            continue

        if is_dicom_candidate(path, max_file_bytes=max_file_bytes):
            summary["candidate_files"] = int(summary["candidate_files"]) + 1
            summary["candidate_bytes"] = int(summary["candidate_bytes"]) + size
        else:
            summary["non_dicom_files"] = int(summary["non_dicom_files"]) + 1
            summary["non_dicom_bytes"] = int(summary["non_dicom_bytes"]) + size
        progress.update(index, message=f"Analyzed {index}/{len(files)} files")

    total_bytes = int(summary["total_bytes"])
    raw_like_bytes = int(summary["oversized_dicom_like_bytes"])
    skipped_bytes = raw_like_bytes + int(summary["oversized_other_bytes"])
    summary["estimated_raw_like_percent"] = (raw_like_bytes / total_bytes * 100.0) if total_bytes else 0.0
    summary["skipped_by_threshold_percent"] = (skipped_bytes / total_bytes * 100.0) if total_bytes else 0.0
    summary["total_size"] = format_bytes(total_bytes)
    summary["candidate_size"] = format_bytes(int(summary["candidate_bytes"]))
    summary["oversized_dicom_like_size"] = format_bytes(raw_like_bytes)
    summary["skipped_by_threshold_size"] = format_bytes(skipped_bytes)
    summary["archive_size"] = format_bytes(int(summary["archive_bytes"]))
    summary["extensions"] = extensions
    summary["largest_oversized"] = largest
    progress.finish("Analysis complete")
    return summary


def analyze_zip_size(
    archive_path: Path,
    max_file_bytes: Optional[int] = DEFAULT_MAX_FILE_BYTES,
    largest_limit: int = 10,
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict[str, object]:
    listing_progress = ProgressTracker(total=0, phase="Reading archive", callback=progress_callback)
    listing_progress.emit()
    if not archive_path.exists():
        return {"exists": False, "message": "Input path does not exist."}

    summary: Dict[str, object] = {
        "exists": True,
        "path": str(archive_path),
        "threshold_bytes": max_file_bytes,
        "threshold": format_bytes(max_file_bytes) if max_file_bytes else "Unlimited",
        "total_files": 0,
        "total_bytes": 0,
        "candidate_files": 0,
        "candidate_bytes": 0,
        "oversized_dicom_like_files": 0,
        "oversized_dicom_like_bytes": 0,
        "oversized_other_files": 0,
        "oversized_other_bytes": 0,
        "non_dicom_files": 0,
        "non_dicom_bytes": 0,
        "artifact_files": 0,
        "artifact_bytes": 0,
        "archive_files": 0,
        "archive_bytes": 0,
        "extensions": {},
        "largest_oversized": [],
    }
    largest: List[Dict[str, object]] = []
    extensions: Dict[str, Dict[str, object]] = {}

    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            members = [member for member in archive.infolist() if not member.is_dir()]
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        return {"exists": False, "message": f"Could not read ZIP archive: {exc}"}
    progress = ProgressTracker(total=len(members), phase="Analyzing", callback=progress_callback)
    progress.emit()

    for index, member in enumerate(members, start=1):
        member_path = Path(member.filename)
        size = int(member.file_size)
        suffix = member_path.suffix.lower() or "[none]"
        ext_stats = extensions.setdefault(suffix, {"files": 0, "bytes": 0})
        ext_stats["files"] = int(ext_stats["files"]) + 1
        ext_stats["bytes"] = int(ext_stats["bytes"]) + size

        summary["total_files"] = int(summary["total_files"]) + 1
        summary["total_bytes"] = int(summary["total_bytes"]) + size

        if is_metadata_artifact(member_path):
            summary["artifact_files"] = int(summary["artifact_files"]) + 1
            summary["artifact_bytes"] = int(summary["artifact_bytes"]) + size
            progress.update(index, message=f"Analyzed {index}/{len(members)} archive entries")
            continue
        if suffix in ARCHIVE_EXTENSIONS:
            summary["archive_files"] = int(summary["archive_files"]) + 1
            summary["archive_bytes"] = int(summary["archive_bytes"]) + size
            progress.update(index, message=f"Analyzed {index}/{len(members)} archive entries")
            continue

        oversized = bool(max_file_bytes and size > max_file_bytes)
        dicom_like = suffix in KNOWN_DICOM_EXTENSIONS
        if oversized:
            item = {
                "path": str(member_path),
                "size_bytes": size,
                "size": format_bytes(size),
                "dicom_like": dicom_like,
            }
            largest.append(item)
            largest.sort(key=lambda entry: int(entry["size_bytes"]), reverse=True)
            del largest[largest_limit:]
            if dicom_like:
                summary["oversized_dicom_like_files"] = int(summary["oversized_dicom_like_files"]) + 1
                summary["oversized_dicom_like_bytes"] = int(summary["oversized_dicom_like_bytes"]) + size
            else:
                summary["oversized_other_files"] = int(summary["oversized_other_files"]) + 1
                summary["oversized_other_bytes"] = int(summary["oversized_other_bytes"]) + size
            progress.update(index, message=f"Analyzed {index}/{len(members)} archive entries")
            continue

        if dicom_like:
            summary["candidate_files"] = int(summary["candidate_files"]) + 1
            summary["candidate_bytes"] = int(summary["candidate_bytes"]) + size
        else:
            summary["non_dicom_files"] = int(summary["non_dicom_files"]) + 1
            summary["non_dicom_bytes"] = int(summary["non_dicom_bytes"]) + size
        progress.update(index, message=f"Analyzed {index}/{len(members)} archive entries")

    total_bytes = int(summary["total_bytes"])
    raw_like_bytes = int(summary["oversized_dicom_like_bytes"])
    skipped_bytes = raw_like_bytes + int(summary["oversized_other_bytes"])
    summary["estimated_raw_like_percent"] = (raw_like_bytes / total_bytes * 100.0) if total_bytes else 0.0
    summary["skipped_by_threshold_percent"] = (skipped_bytes / total_bytes * 100.0) if total_bytes else 0.0
    summary["total_size"] = format_bytes(total_bytes)
    summary["candidate_size"] = format_bytes(int(summary["candidate_bytes"]))
    summary["oversized_dicom_like_size"] = format_bytes(raw_like_bytes)
    summary["skipped_by_threshold_size"] = format_bytes(skipped_bytes)
    summary["archive_size"] = format_bytes(int(summary["archive_bytes"]))
    summary["extensions"] = extensions
    summary["largest_oversized"] = largest
    progress.finish("Analysis complete")
    return summary


def analyze_7z_size(
    archive_path: Path,
    max_file_bytes: Optional[int] = DEFAULT_MAX_FILE_BYTES,
    largest_limit: int = 10,
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict[str, object]:
    listing_progress = ProgressTracker(total=0, phase="Reading archive", callback=progress_callback)
    listing_progress.emit()
    if not archive_path.exists():
        return {"exists": False, "message": "Input path does not exist."}
    try:
        import py7zr  # type: ignore[import]
        with py7zr.SevenZipFile(archive_path, mode="r") as archive:
            members = [
                item
                for item in archive.list()
                if not getattr(item, "is_directory", False)
            ]
    except Exception as exc:
        return {"exists": False, "message": f"Could not read 7Z archive: {exc}"}

    summary: Dict[str, object] = {
        "exists": True,
        "path": str(archive_path),
        "threshold_bytes": max_file_bytes,
        "threshold": format_bytes(max_file_bytes) if max_file_bytes else "Unlimited",
        "total_files": 0,
        "total_bytes": 0,
        "candidate_files": 0,
        "candidate_bytes": 0,
        "oversized_dicom_like_files": 0,
        "oversized_dicom_like_bytes": 0,
        "oversized_other_files": 0,
        "oversized_other_bytes": 0,
        "non_dicom_files": 0,
        "non_dicom_bytes": 0,
        "artifact_files": 0,
        "artifact_bytes": 0,
        "archive_files": 0,
        "archive_bytes": 0,
        "extensions": {},
        "largest_oversized": [],
    }
    largest: List[Dict[str, object]] = []
    extensions: Dict[str, Dict[str, object]] = {}
    progress = ProgressTracker(total=len(members), phase="Analyzing", callback=progress_callback)
    progress.emit()

    for index, member in enumerate(members, start=1):
        member_path = Path(str(getattr(member, "filename", "")))
        size = int(getattr(member, "uncompressed", 0) or 0)
        suffix = member_path.suffix.lower() or "[none]"
        ext_stats = extensions.setdefault(suffix, {"files": 0, "bytes": 0})
        ext_stats["files"] = int(ext_stats["files"]) + 1
        ext_stats["bytes"] = int(ext_stats["bytes"]) + size
        summary["total_files"] = int(summary["total_files"]) + 1
        summary["total_bytes"] = int(summary["total_bytes"]) + size

        if is_metadata_artifact(member_path):
            summary["artifact_files"] = int(summary["artifact_files"]) + 1
            summary["artifact_bytes"] = int(summary["artifact_bytes"]) + size
            progress.update(index, message=f"Analyzed {index}/{len(members)} archive entries")
            continue
        if suffix in ARCHIVE_EXTENSIONS:
            summary["archive_files"] = int(summary["archive_files"]) + 1
            summary["archive_bytes"] = int(summary["archive_bytes"]) + size
            progress.update(index, message=f"Analyzed {index}/{len(members)} archive entries")
            continue

        oversized = bool(max_file_bytes and size > max_file_bytes)
        dicom_like = suffix in KNOWN_DICOM_EXTENSIONS
        if oversized:
            item = {"path": str(member_path), "size_bytes": size, "size": format_bytes(size), "dicom_like": dicom_like}
            largest.append(item)
            largest.sort(key=lambda entry: int(entry["size_bytes"]), reverse=True)
            del largest[largest_limit:]
            if dicom_like:
                summary["oversized_dicom_like_files"] = int(summary["oversized_dicom_like_files"]) + 1
                summary["oversized_dicom_like_bytes"] = int(summary["oversized_dicom_like_bytes"]) + size
            else:
                summary["oversized_other_files"] = int(summary["oversized_other_files"]) + 1
                summary["oversized_other_bytes"] = int(summary["oversized_other_bytes"]) + size
            progress.update(index, message=f"Analyzed {index}/{len(members)} archive entries")
            continue

        if dicom_like:
            summary["candidate_files"] = int(summary["candidate_files"]) + 1
            summary["candidate_bytes"] = int(summary["candidate_bytes"]) + size
        else:
            summary["non_dicom_files"] = int(summary["non_dicom_files"]) + 1
            summary["non_dicom_bytes"] = int(summary["non_dicom_bytes"]) + size
        progress.update(index, message=f"Analyzed {index}/{len(members)} archive entries")

    total_bytes = int(summary["total_bytes"])
    raw_like_bytes = int(summary["oversized_dicom_like_bytes"])
    skipped_bytes = raw_like_bytes + int(summary["oversized_other_bytes"])
    summary["estimated_raw_like_percent"] = (raw_like_bytes / total_bytes * 100.0) if total_bytes else 0.0
    summary["skipped_by_threshold_percent"] = (skipped_bytes / total_bytes * 100.0) if total_bytes else 0.0
    summary["total_size"] = format_bytes(total_bytes)
    summary["candidate_size"] = format_bytes(int(summary["candidate_bytes"]))
    summary["oversized_dicom_like_size"] = format_bytes(raw_like_bytes)
    summary["skipped_by_threshold_size"] = format_bytes(skipped_bytes)
    summary["archive_size"] = format_bytes(int(summary["archive_bytes"]))
    summary["extensions"] = extensions
    summary["largest_oversized"] = largest
    progress.finish("Analysis complete")
    return summary

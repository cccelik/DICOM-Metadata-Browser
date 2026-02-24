from pathlib import Path
from typing import List, Optional

import pydicom
from pydicom.errors import InvalidDicomError

KNOWN_DICOM_EXTENSIONS = {".dcm", ".ima"}
IGNORED_FILENAMES = {".ds_store"}


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


def can_parse_as_dicom(path: Path) -> bool:
    try:
        pydicom.dcmread(path, stop_before_pixels=True, force=True)
        return True
    except (InvalidDicomError, OSError, PermissionError, ValueError):
        return False


def is_dicom_candidate(path: Path) -> bool:
    if not path.is_file() or path.is_symlink() or is_metadata_artifact(path):
        return False

    suffix = path.suffix.lower()
    if suffix in KNOWN_DICOM_EXTENSIONS:
        return True
    if has_dicom_signature(path):
        return True
    if not suffix:
        return can_parse_as_dicom(path)
    return False


def collect_dicom_files(
    root: Path,
    recursive: bool = True,
    limit: Optional[int] = None,
) -> List[Path]:
    if not root.is_dir():
        return []

    matched: List[Path] = []
    iterator = root.rglob("*") if recursive else root.iterdir()
    for file_path in iterator:
        if not is_dicom_candidate(file_path):
            continue
        matched.append(file_path)
        if limit is not None and len(matched) >= limit:
            break
    return matched

"""Helpers for command-line path arguments."""

import glob
import re
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


def expand_path_patterns(values: Iterable[str | Path]) -> List[Path]:
    """Expand shell-style wildcard patterns and return resolved paths.

    Shells differ in whether they expand wildcards before launching Python.
    This helper also expands quoted patterns such as "USB1?" inside the script.
    Unmatched values are returned unchanged so the caller can report its normal
    validation error.
    """
    paths: List[Path] = []
    seen = set()
    for value in values:
        raw = str(value)
        expanded = glob.glob(str(Path(raw).expanduser()))
        candidates = sorted(expanded) if expanded else [raw]
        for candidate in candidates:
            path = Path(candidate).expanduser().resolve()
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            paths.append(path)
    return paths


def looks_like_db_path(value: str) -> bool:
    return Path(value).suffix.lower() in {".db", ".sqlite", ".sqlite3"}


def safe_path_name(value: str) -> str:
    """Return a filesystem-friendly name derived from user-facing input."""
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return name.strip("._") or "dicom_input"


def split_inputs_and_optional_db(
    positionals: List[str],
    explicit_db_path: Optional[str],
    default_db_path: str,
) -> Tuple[List[Path], str]:
    """Split wildcard-capable input arguments from an optional databank path."""
    if explicit_db_path:
        return expand_path_patterns(positionals), explicit_db_path
    if len(positionals) >= 2 and looks_like_db_path(positionals[-1]):
        return expand_path_patterns(positionals[:-1]), positionals[-1]
    if len(positionals) == 2:
        first_matches = expand_path_patterns([positionals[0]])
        second_matches = expand_path_patterns([positionals[1]])
        if len(first_matches) == 1 and first_matches[0].exists() and not second_matches[0].exists():
            return first_matches, positionals[1]
    return expand_path_patterns(positionals), default_db_path

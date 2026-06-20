"""Archive extraction safety helpers."""

from pathlib import Path


def safe_archive_member_path(output_dir: Path, member_name: str) -> Path:
    """Return the resolved member path, rejecting path traversal entries."""
    output_root = output_dir.resolve()
    member_path = (output_root / member_name).resolve()
    if output_root != member_path and output_root not in member_path.parents:
        raise ValueError(f"Unsafe archive member path: {member_name}")
    return member_path

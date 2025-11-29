"""Utility helpers for working with PDF files and derived images."""
from __future__ import annotations

import pathlib
from typing import Iterable, List


def ensure_directory(path: str | pathlib.Path) -> pathlib.Path:
    """Ensure that the directory for the given path exists."""
    target = pathlib.Path(path)
    if target.suffix:
        target = target.parent
    target.mkdir(parents=True, exist_ok=True)
    return target


def cleanup_files(paths: Iterable[str | pathlib.Path]) -> None:
    """Delete the files in *paths*, ignoring missing ones."""
    for raw in paths:
        try:
            pathlib.Path(raw).unlink(missing_ok=True)  # type: ignore[arg-type]
        except PermissionError:
            continue


def derive_temp_path(base_dir: str | pathlib.Path, stem: str, suffix: str) -> pathlib.Path:
    base = pathlib.Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)
    stem = stem.replace("/", "_").replace("\\", "_")
    return base / f"{stem}{suffix}"
"""Helpers for extracting structured data from lab PDFs."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import fitz  # type: ignore


_REFERENCE_CACHE: Dict[str, Dict[str, Any]] = {}

REFERENCE_CANDIDATES: Tuple[Path, ...] = (
    PROJECT_ROOT / "instance" / "references.json",
    PROJECT_ROOT / "references.json",
    PROJECT_ROOT / "static" / "references.json",
    PROJECT_ROOT / "data" / "references.json",
)


class ReferenceNotFoundError(RuntimeError):
    """Raised when references.json is missing."""


def _locate_references() -> str:
    for candidate in REFERENCE_CANDIDATES:
        if candidate.exists():
            return str(candidate)
    raise ReferenceNotFoundError(
        "references.json not found. Place it under 'instance/' or the project root."
    )


def _load_reference_payload(path: str) -> Dict[str, Any]:
    cached = _REFERENCE_CACHE.get(path)
    if cached:
        return cached
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    data = payload.get("tests") if isinstance(payload, dict) and isinstance(payload.get("tests"), dict) else payload
    if not isinstance(data, dict):
        raise RuntimeError("Invalid references payload — expected mapping with test definitions.")
    _REFERENCE_CACHE[path] = data  # shallow cache is enough for a single process
    return data


def _extract_full_text(file_bytes: bytes) -> str:
    try:
        with fitz.open(stream=file_bytes, filetype="pdf") as doc:
            chunks = []
            for page in doc:
                chunks.append(page.get_text("text"))
        return "\n".join(chunks).strip()
    except Exception:
        return ""


def extract_exam_payload(file_bytes: bytes, *, require_ocr: bool = False) -> Dict[str, Any]:
    """Return the raw PDF text so the AI can interpret it directly."""
    if not file_bytes:
        raise ValueError("PDF vazio ou corrompido.")
    references_path = _locate_references()
    raw_text = _extract_full_text(file_bytes)
    references_raw = _load_reference_payload(references_path)
    return {
        "patient": {},
        "lab_results": [],
        "suggestions": [],
        "raw_text": raw_text,
        "reference_table": references_raw,
        "references_path": references_path,
        "artifacts": {"ocr": 0, "ocr_pages": 0, "blocks": 0},
        "gender_hint": None,
    }

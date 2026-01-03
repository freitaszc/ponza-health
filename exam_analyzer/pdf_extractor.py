"""Helpers for extracting structured data from lab PDFs."""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

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


def _merge_patient_payload(base: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    if not incoming:
        return base
    mapping = {
        "nome": ("nome", "name"),
        "sexo": ("sexo", "gender"),
        "data_nascimento": ("data_nascimento", "birth_date"),
        "telefone": ("telefone", "phone"),
        "cpf": ("cpf", "cpf"),
    }
    merged = dict(base)
    for target_key, candidates in mapping.items():
        if merged.get(target_key):
            continue
        for key in candidates:
            value = incoming.get(key)
            if value:
                merged[target_key] = value
                break
    return merged


def _normalize_lab_results(raw_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        name = item.get("nome") or item.get("name") or item.get("test")
        if not name:
            continue
        normalized.append({
            "nome": name,
            "valor": item.get("valor") if "valor" in item else item.get("value"),
            "unidade": item.get("unidade") if "unidade" in item else item.get("unit"),
            "referencia": item.get("referencia") if "referencia" in item else item.get("reference"),
            "raw_line": item.get("raw_line") or item.get("source") or item.get("raw"),
        })
    return normalized


def _should_enrich_extraction(patient: Dict[str, Any], lab_results: List[Dict[str, Any]]) -> bool:
    min_results = int(os.getenv("EXAM_ANALYSIS_MIN_RESULTS", "4"))
    if len(lab_results) < min_results:
        return True
    if any(patient.get(key) for key in ("nome", "cpf", "data_nascimento", "sexo", "telefone")):
        return False
    return True


PATIENT_KEYWORDS = (
    "paciente",
    "nome",
    "cpf",
    "sexo",
    "nascimento",
    "idade",
    "data nasc",
    "data de nascimento",
)

RESULT_HINTS = ("ref", "refer", "valor", "resultado", "vr")

RESULT_LINE_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9 /().%-]{2,}?)\s*[:\-–]\s*"
    r"(?P<value>[-+]?\d[\d.,]*)\s*"
    r"(?P<unit>[A-Za-z/%\^0-9]+)?"
    r"(?:\s*(?:\(|\[)?(?:ref|vr|refer(?:encia)?|valor(?:es)? de ref)[:\s]*"
    r"(?P<ref>[^\)\]]+))?",
    re.IGNORECASE,
)


def _clean_lines(raw_text: str) -> List[str]:
    lines = []
    for line in raw_text.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        if len(cleaned) > 180:
            cleaned = cleaned[:180] + "..."
        lines.append(cleaned)
    return lines


def _extract_key_lines(raw_text: str) -> Dict[str, List[str]]:
    lines = _clean_lines(raw_text)
    patient_lines: List[str] = []
    result_lines: List[str] = []
    for line in lines:
        lower = line.lower()
        if any(keyword in lower for keyword in PATIENT_KEYWORDS):
            patient_lines.append(line)
            continue
        if any(char.isdigit() for char in line):
            if any(hint in lower for hint in RESULT_HINTS) or ":" in line or "-" in line:
                result_lines.append(line)
                continue
            # Keep numeric lines with letters even if they don't have a hint/colon.
            if any(char.isalpha() for char in line):
                result_lines.append(line)
    return {"patient_lines": patient_lines, "result_lines": result_lines}


def _parse_patient_info(lines: List[str]) -> Dict[str, Any]:
    patient: Dict[str, Any] = {}
    for line in lines:
        lower = line.lower()
        if "cpf" in lower and "cpf" not in patient:
            parts = line.split(":")
            if len(parts) > 1:
                patient["cpf"] = parts[-1].strip()
        if ("nome" in lower or "paciente" in lower) and "nome" not in patient:
            parts = line.split(":")
            if len(parts) > 1:
                patient["nome"] = parts[-1].strip()
        if ("sexo" in lower) and "sexo" not in patient:
            parts = line.split(":")
            if len(parts) > 1:
                patient["sexo"] = parts[-1].strip()
        if ("nascimento" in lower or "data nasc" in lower) and "data_nascimento" not in patient:
            parts = line.split(":")
            if len(parts) > 1:
                patient["data_nascimento"] = parts[-1].strip()
    return patient


def _parse_result_lines(lines: List[str]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for line in lines:
        match = RESULT_LINE_RE.match(line)
        if match:
            data = match.groupdict()
            results.append({
                "nome": (data.get("name") or "").strip(),
                "valor": (data.get("value") or "").strip(),
                "unidade": (data.get("unit") or "").strip(),
                "referencia": (data.get("ref") or "").strip(),
                "raw_line": line,
            })
            continue
        tokens = line.split()
        for idx, token in enumerate(tokens):
            if re.match(r"^[-+]?\d[\d.,]*$", token):
                name = " ".join(tokens[:idx]).strip()
                unit = tokens[idx + 1] if idx + 1 < len(tokens) else ""
                reference = " ".join(tokens[idx + 2 :]) if idx + 2 < len(tokens) else ""
                if name:
                    results.append({
                        "nome": name,
                        "valor": token,
                        "unidade": unit,
                        "referencia": reference,
                        "raw_line": line,
                    })
                break
    return results


def extract_exam_payload(
    file_bytes: bytes,
    *,
    require_ocr: bool = False,
    timings: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Return structured excerpts for the AI (avoid raw full text)."""
    if not file_bytes:
        raise ValueError("PDF vazio ou corrompido.")
    references_path = _locate_references()
    timings = timings or {}
    extract_start = time.perf_counter()
    raw_text = _extract_full_text(file_bytes)
    timings["pdf_extract_ms"] = round((time.perf_counter() - extract_start) * 1000)

    key_lines = _extract_key_lines(raw_text)
    patient = _parse_patient_info(key_lines.get("patient_lines") or [])
    lab_results = _parse_result_lines(key_lines.get("result_lines") or [])
    max_results = int(os.getenv("EXAM_ANALYSIS_MAX_RESULTS", "120"))
    if len(lab_results) > max_results:
        lab_results = lab_results[:max_results]

    structured_ms = 0
    ocr_ms = 0
    ocr_pages = 0
    should_enrich = _should_enrich_extraction(patient, lab_results)
    if should_enrich:
        try:
            from pdf_pipeline.structured_extractor import run_pipeline

            structured_start = time.perf_counter()
            pipeline = run_pipeline(file_bytes, references_path, require_ocr=False)
            structured_ms = round((time.perf_counter() - structured_start) * 1000)
            raw_text = pipeline.raw_text or raw_text
            patient = _merge_patient_payload(patient, pipeline.patient_data or {})
            pipeline_results = _normalize_lab_results(pipeline.lab_results or [])
            if pipeline_results:
                lab_results = pipeline_results
        except Exception:
            structured_ms = 0

    min_chars = int(os.getenv("EXAM_ANALYSIS_OCR_MIN_CHARS", "200"))
    if require_ocr or len(raw_text) < min_chars or _should_enrich_extraction(patient, lab_results):
        try:
            from pdf_pipeline.structured_extractor import run_pipeline

            ocr_start = time.perf_counter()
            pipeline = run_pipeline(file_bytes, references_path, require_ocr=True)
            ocr_ms = round((time.perf_counter() - ocr_start) * 1000)
            raw_text = pipeline.raw_text or raw_text
            patient = _merge_patient_payload(patient, pipeline.patient_data or {})
            pipeline_results = _normalize_lab_results(pipeline.lab_results or [])
            if pipeline_results:
                lab_results = pipeline_results
            ocr_pages = pipeline.artifacts.ocr_pages
        except Exception:
            ocr_ms = 0

    if structured_ms:
        timings["structured_extract_ms"] = structured_ms
    if ocr_ms:
        timings["ocr_ms"] = ocr_ms

    key_lines = _extract_key_lines(raw_text)
    if len(lab_results) > max_results:
        lab_results = lab_results[:max_results]

    references_raw = _load_reference_payload(references_path)
    merged_lines = (key_lines.get("patient_lines") or []) + (key_lines.get("result_lines") or [])
    max_lines = int(os.getenv("EXAM_ANALYSIS_MAX_LINES", "200"))
    max_excerpt = int(os.getenv("EXAM_ANALYSIS_MAX_EXCERPT_CHARS", "6000"))
    include_raw_excerpt = _should_enrich_extraction(patient, lab_results)
    return {
        "patient": patient,
        "lab_results": lab_results,
        "suggestions": [],
        "key_lines": merged_lines[:max_lines],
        "raw_excerpt": raw_text[:max_excerpt],
        "include_raw_excerpt": include_raw_excerpt,
        "reference_table": references_raw,
        "references_path": references_path,
        "artifacts": {
            "ocr": 1 if ocr_ms else 0,
            "ocr_pages": ocr_pages,
            "blocks": 0,
            "ocr_ms": ocr_ms,
        },
        "gender_hint": None,
        "timings": timings,
    }

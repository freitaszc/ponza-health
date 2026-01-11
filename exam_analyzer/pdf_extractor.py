"""Helpers for extracting structured data from lab PDFs."""
from __future__ import annotations

import json
import os
import re
import sys
import time
from io import BytesIO
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

# Multiple patterns to capture different formats of lab results
RESULT_LINE_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9 /().%-]{2,}?)\s*[:\-–]\s*"
    r"(?P<value>[-+]?\d[\d.,]*)\s*"
    r"(?P<unit>[A-Za-z/%\^0-9]+)?"
    r"(?:\s*(?:\(|\[)?(?:ref|vr|refer(?:encia)?|valor(?:es)? de ref)[:\s]*"
    r"(?P<ref>[^\)\]]+))?",
    re.IGNORECASE,
)

# Pattern for values with multiple decimals and ranges
COMPLEX_VALUE_RE = re.compile(
    r"(?P<value>[-+]?\d+[.,]\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>[A-Za-z/%\^0-9µμ]+)?"
)

# Pattern to detect reference ranges (e.g., 150-250, < 100, > 50)
REFERENCE_PATTERN_RE = re.compile(
    r"(?:ref|refer(?:encia)?|vr|valor de ref)[:\s]*"
    r"(?P<ref_min>[-+]?\d+[.,]?\d*)\s*[-–a-z]*\s*(?P<ref_max>[-+]?\d+[.,]?\d*)|"
    r"(?:ref|refer(?:encia)?|vr)[:\s]*"
    r"(?P<ref_simple>[<>]=?[-+]?\d+[.,]?\d*|[-+]?\d+[.,]?\d*)",
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
        
        # Extract patient info
        if any(keyword in lower for keyword in PATIENT_KEYWORDS):
            patient_lines.append(line)
            continue
        
        # Enhanced detection: look for lines with numbers (values)
        has_digit = any(char.isdigit() for char in line)
        if not has_digit:
            continue
            
        # Strong indicators this is a result line
        has_result_hint = any(hint in lower for hint in RESULT_HINTS)
        has_separator = ":" in line or "-" in line or "–" in line
        
        # Include if it matches strong patterns
        if has_result_hint or has_separator:
            result_lines.append(line)
            continue
        
        # Include numeric lines with letters (may be test results)
        has_letters = any(char.isalpha() for char in line)
        if has_letters:
            # Exclude common non-result lines
            if not any(x in lower for x in ["página", "total de", "análise", "data:", "hora:", "solicitação", "laboratório"]):
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
        # Try the main regex pattern first
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
        
        # Fallback: try to extract from space-separated or comma-separated values
        # Handle cases like: "Hemoglobina 14.5 g/dL ref: 12-16"
        tokens = line.split()
        
        for idx, token in enumerate(tokens):
            # Look for numeric tokens (potential values)
            if re.match(r"^[-+]?\d[\d.,]*$", token):
                name = " ".join(tokens[:idx]).strip()
                value = token
                
                # Try to get unit (next token if it's not a number)
                unit = ""
                ref = ""
                
                if idx + 1 < len(tokens):
                    next_token = tokens[idx + 1]
                    # Check if it looks like a unit
                    if not re.match(r"^[-+]?\d", next_token) and not any(x in next_token.lower() for x in ["ref", "vr", "refer"]):
                        unit = next_token
                        # Everything after is potential reference
                        if idx + 2 < len(tokens):
                            ref = " ".join(tokens[idx + 2:])
                    else:
                        # Next token is also numeric or a reference marker
                        ref = " ".join(tokens[idx + 1:])
                
                if name and name.lower() not in ["página", "total", "análise"]:
                    results.append({
                        "nome": name,
                        "valor": value,
                        "unidade": unit,
                        "referencia": ref,
                        "raw_line": line,
                    })
                    break
    
    return results


def _extract_table_results(file_bytes: bytes) -> List[Dict[str, Any]]:
    """Extract lab results from tables in PDF (common format for lab reports)."""
    results: List[Dict[str, Any]] = []
    try:
        import pdfplumber
        with pdfplumber.open(file_bytes if isinstance(file_bytes, (str, Path)) else BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                if not tables:
                    continue
                
                for table in tables:
                    if not table or len(table) < 2:
                        continue
                    
                    # Detect header row (usually first row)
                    headers = [str(h).lower().strip() if h else "" for h in table[0]]
                    
                    # Look for typical column patterns
                    test_col = next((i for i, h in enumerate(headers) if any(x in h for x in ["teste", "exame", "test", "name", "analítico", "parâmetro"])), 0)
                    value_col = next((i for i, h in enumerate(headers) if any(x in h for x in ["resultado", "valor", "result", "value"])), 1)
                    unit_col = next((i for i, h in enumerate(headers) if any(x in h for x in ["unidade", "unit"])), -1)
                    ref_col = next((i for i, h in enumerate(headers) if any(x in h for x in ["referência", "ref", "reference", "normal"])), -1)
                    
                    # Extract rows
                    for row in table[1:]:
                        if not row or all(not cell for cell in row):
                            continue
                        
                        test_name = str(row[test_col] or "").strip() if test_col < len(row) else ""
                        test_value = str(row[value_col] or "").strip() if value_col < len(row) else ""
                        test_unit = str(row[unit_col] or "").strip() if unit_col >= 0 and unit_col < len(row) else ""
                        test_ref = str(row[ref_col] or "").strip() if ref_col >= 0 and ref_col < len(row) else ""
                        
                        # Validate we have at least name and value
                        if test_name and test_value and re.search(r"\d", test_value):
                            results.append({
                                "nome": test_name,
                                "valor": test_value,
                                "unidade": test_unit,
                                "referencia": test_ref,
                                "raw_line": f"[TABLE] {test_name} {test_value}",
                            })
    except Exception:
        pass
    
    return results


def extract_exam_payload(
    file_bytes: bytes,
    *,
    require_ocr: bool = False,
    timings: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Return structured excerpts for the AI using plain PDF text + OCR when needed."""
    if not file_bytes:
        raise ValueError("PDF vazio ou corrompido.")
    references_path = _locate_references()
    timings = timings or {}
    extract_start = time.perf_counter()
    raw_text = _extract_full_text(file_bytes)
    timings["pdf_extract_ms"] = round((time.perf_counter() - extract_start) * 1000)

    max_results = int(os.getenv("EXAM_ANALYSIS_MAX_RESULTS", "120"))
    ocr_ms = 0
    ocr_pages = 0

    min_chars = int(os.getenv("EXAM_ANALYSIS_OCR_MIN_CHARS", "200"))
    needs_ocr = require_ocr or len(raw_text) < min_chars
    if needs_ocr:
        try:
            from pdf_pipeline.structured_extractor import run_pipeline

            ocr_start = time.perf_counter()
            pipeline = run_pipeline(file_bytes, references_path, require_ocr=True)
            ocr_ms = round((time.perf_counter() - ocr_start) * 1000)
            if pipeline.raw_text:
                raw_text = pipeline.raw_text
            ocr_pages = getattr(pipeline.artifacts, "ocr_pages", 0)
        except Exception:
            ocr_ms = 0

    if ocr_ms:
        timings["ocr_ms"] = ocr_ms

    key_lines = _extract_key_lines(raw_text)
    patient = _parse_patient_info(key_lines.get("patient_lines") or [])
    lab_results = _parse_result_lines(key_lines.get("result_lines") or [])
    
    # Try to extract results from tables as well (common in lab reports)
    table_results = _extract_table_results(file_bytes)
    
    # Merge results, avoiding duplicates
    existing_names = {r.get("nome", "").lower().strip() for r in lab_results}
    for table_result in table_results:
        table_name = table_result.get("nome", "").lower().strip()
        # Add if it's not already captured
        if table_name and table_name not in existing_names:
            lab_results.append(table_result)
            existing_names.add(table_name)
    
    if len(lab_results) > max_results:
        lab_results = lab_results[:max_results]

    references_raw = _load_reference_payload(references_path)
    merged_lines = (key_lines.get("patient_lines") or []) + (key_lines.get("result_lines") or [])
    max_lines = int(os.getenv("EXAM_ANALYSIS_MAX_LINES", "200"))
    max_excerpt = int(os.getenv("EXAM_ANALYSIS_MAX_EXCERPT_CHARS", "6000"))
    return {
        "patient": patient,
        "lab_results": lab_results,
        "suggestions": [],
        "key_lines": merged_lines[:max_lines],
        "raw_excerpt": raw_text[:max_excerpt],
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

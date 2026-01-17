"""Helpers for extracting structured data from lab PDFs."""
from __future__ import annotations

import json
import os
import re
import sys
import time
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

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


def _extract_text_with_layout(file_bytes: bytes) -> str:
    """Extract text preserving layout structure (better for columnar data)."""
    try:
        with fitz.open(stream=file_bytes, filetype="pdf") as doc:
            chunks = []
            for page in doc:
                # Use "dict" mode for better structure understanding
                blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
                page_text = []
                for block in blocks.get("blocks", []):
                    if block.get("type") == 0:  # text block
                        for line in block.get("lines", []):
                            line_text = " ".join(
                                span.get("text", "") for span in line.get("spans", [])
                            )
                            if line_text.strip():
                                page_text.append(line_text)
                chunks.append("\n".join(page_text))
        return "\n\n".join(chunks).strip()
    except Exception:
        return _extract_full_text(file_bytes)


PATIENT_KEYWORDS = (
    "paciente",
    "nome",
    "cpf",
    "sexo",
    "nascimento",
    "idade",
    "data nasc",
    "data de nascimento",
    "telefone",
    "tel",
    "celular",
    "rg",
    "cliente",
    "solicitante",
)

RESULT_HINTS = ("ref", "refer", "valor", "resultado", "vr", "normal", "ideal")

# Skip lines containing these patterns (headers, metadata, etc.)
SKIP_LINE_PATTERNS = [
    r"^página\s*\d+",
    r"^pag\s*\.",
    r"^data\s*de\s*(?:coleta|emissão|impressão)",
    r"^laboratório",
    r"^laudo\s*(?:nº|numero|n°)",
    r"^solicitante",
    r"^médico",
    r"^crm",
    r"^material\s*:",
    r"^método\s*:",
    r"^observa[çc][ãa]o\s*:",
    r"^nota\s*:",
    r"^\*+",
    r"^assinatura",
    r"^responsável",
]
SKIP_LINE_RE = re.compile("|".join(SKIP_LINE_PATTERNS), re.IGNORECASE)

# Multiple patterns to capture different formats of lab results
# Pattern 1: Name : Value Unit (Ref: xxx)
RESULT_LINE_RE = re.compile(
    r"^(?P<name>[A-Za-zÀ-ÿ0-9 /().,%+-]{2,}?)\s*[:\-–—]\s*"
    r"(?P<value>(?:<=|>=|<|>)?\s*[-+]?\d[\d.,]*)\s*"
    r"(?P<unit>[A-Za-z/%\^0-9µμ]+)?"
    r"(?:\s*(?:\(|\[)?(?:ref|vr|refer(?:encia)?|valor(?:es)? de ref)[:\s]*"
    r"(?P<ref>[^\)\]]+))?",
    re.IGNORECASE,
)

# Pattern 2: Flexible pattern for various lab formats
RESULT_FLEXIBLE_RE = re.compile(
    r"(?P<name>[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9 /().,%+-]{1,50}?)"
    r"[\s:.\-–—]+"
    r"(?P<value>(?:<=|>=|<|>)?\s*[-+]?\d[\d.,]*(?:\s*[xX]\s*10\^\d+)?)"
    r"(?:\s*(?P<unit>[A-Za-z/%\^µμ][A-Za-z0-9/%\^µμ³]*))?"
    r"(?:\s+(?P<ref>[\d.,]+\s*[-–a-z]+\s*[\d.,]+|[<>]=?\s*[\d.,]+))?",
    re.IGNORECASE,
)

# Pattern 3: For columnar layouts (Name    Value    Unit    Reference)
COLUMNAR_RE = re.compile(
    r"^(?P<name>[A-Za-zÀ-ÿ][^\d]{2,30}?)\s{2,}"
    r"(?P<value>(?:<=|>=|<|>)?\s*[-+]?\d[\d.,]*)\s*"
    r"(?:(?P<unit>[A-Za-z/%µμ][A-Za-z0-9/%µμ³/]*)\s*)?"
    r"(?:(?P<ref>[\d.,\s\-–<>]+))?",
    re.IGNORECASE,
)

# Pattern for values with multiple decimals and ranges
COMPLEX_VALUE_RE = re.compile(
    r"(?P<value>[-+]?\d+[.,]\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>[A-Za-z/%\^0-9µμ]+)?"
)

# Pattern to detect reference ranges (e.g., 150-250, < 100, > 50)
REFERENCE_PATTERN_RE = re.compile(
    r"(?:ref|refer[êe]?n?cia|vr|valor(?:es)?\s*(?:de\s*)?ref(?:erência)?|normal)[:\s]*"
    r"(?P<ref_range>[\d.,]+\s*[-–a]\s*[\d.,]+|[<>]=?\s*[\d.,]+|[\d.,]+)"
    r"|"
    r"(?P<ref_min>[-+]?\d+[.,]?\d*)\s*[-–a]\s*(?P<ref_max>[-+]?\d+[.,]?\d*)",
    re.IGNORECASE,
)

# Enhanced patient label regex with more patterns
PATIENT_LABEL_RE = re.compile(
    r"\b(paciente|nome(?:\s+(?:completo|do\s+paciente))?|cpf|sexo|nascimento|"
    r"data\s*(?:de\s*)?nasc(?:imento)?|idade|telefone|tel\.?|celular|rg|"
    r"cliente|gênero|genero)\b",
    re.IGNORECASE,
)

VALUE_TOKEN_RE = re.compile(r"(?:<=|>=|<|>)?\s*[-+]?\d[\d.,]*")

SKIP_RESULT_NAMES = {
    "página",
    "total",
    "análise",
    "resultado",
    "resultados",
    "valor",
    "unidade",
    "referencia",
    "referência",
}


def _clean_patient_value(value: str) -> str:
    cleaned = value.strip()
    cleaned = cleaned.strip(":-|;")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


# Common exam names that should NOT be confused with patient names
EXAM_NAME_KEYWORDS = {
    "hemoglobina", "glicose", "glicada", "colesterol", "triglicerídeos", "triglicerideos",
    "creatinina", "ureia", "ácido", "acido", "úrico", "urico", "tsh", "t3", "t4",
    "hemácias", "hemacias", "leucócitos", "leucocitos", "plaquetas", "vitamina",
    "ferro", "ferritina", "sódio", "sodio", "potássio", "potassio", "cálcio", "calcio",
    "magnésio", "magnesio", "fósforo", "fosforo", "bilirrubina", "tgo", "tgp", "ggt",
    "fosfatase", "proteína", "proteina", "albumina", "globulina", "ldh", "cpk",
    "amilase", "lipase", "psa", "hba1c", "pcr", "vhs", "hemograma", "eritrócitos",
    "eritrocitos", "hematócrito", "hematocrito", "vcm", "hcm", "chcm", "rdw",
    "neutrófilos", "neutrofilos", "linfócitos", "linfocitos", "monócitos", "monocitos",
    "eosinófilos", "eosinofilos", "basófilos", "basofilos", "glicemia", "insulina",
    "cortisol", "prolactina", "testosterona", "estradiol", "progesterona", "fsh", "lh",
    "urina", "fezes", "hdl", "ldl", "vldl", "gli", "hb", "ht", "vcm"
}


def _is_exam_name(value: str) -> bool:
    """Check if a value looks like an exam name rather than a person's name."""
    if not value:
        return False
    lower = value.lower()
    # Check if any exam keyword is in the value
    for keyword in EXAM_NAME_KEYWORDS:
        if keyword in lower:
            return True
    # Check if it looks like a numeric value or measurement
    if re.search(r"\d+[.,]\d+|\d+\s*(mg|g|dl|ml|mm|%|u/l|ui/l)", lower):
        return True
    return False


def _extract_patient_fields_from_line(line: str) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    matches = list(PATIENT_LABEL_RE.finditer(line))
    if not matches:
        return fields
    leading_ws = len(line) - len(line.lstrip())
    for idx, match in enumerate(matches):
        label = match.group(1).lower()
        label_pos = match.start()
        tail = line[match.end():]
        has_separator = bool(re.match(r"\s*[:\-]", tail))
        effective_pos = max(0, label_pos - leading_ws)
        if not has_separator and effective_pos > 2:
            continue
        if label == "idade" and not has_separator and "anos de idade" in line.lower():
            continue
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(line)
        raw_value = _clean_patient_value(line[start:end])
        if not raw_value:
            continue
        if label in ("paciente", "nome"):
            key = "nome"
            value = raw_value
            # Skip if this looks like an exam name
            if _is_exam_name(value):
                continue
        elif "nasc" in label:
            key = "data_nascimento"
            value = raw_value
        elif label == "sexo":
            key = "sexo"
            value = raw_value.split()[0] if raw_value else raw_value
        elif label == "cpf":
            key = "cpf"
            cpf_match = re.search(r"\d{3}\.?\d{3}\.?\d{3}-?\d{2}", raw_value)
            value = cpf_match.group(0) if cpf_match else raw_value
        elif label in ("telefone", "tel", "celular"):
            key = "telefone"
            phone_match = re.search(r"\(?\d{2}\)?\s*\d{4,5}[-\s]?\d{4}", raw_value)
            value = phone_match.group(0) if phone_match else raw_value
        elif label == "idade":
            key = "idade"
            value = raw_value
        elif label == "rg":
            key = "rg"
            value = raw_value
        else:
            continue
        if value and key not in fields:
            fields[key] = value
    return fields


def _extract_reference(line: str) -> str:
    match = REFERENCE_PATTERN_RE.search(line)
    if not match:
        return ""
    # Use lastgroup to check which alternative matched, or check groups safely
    groups = match.groupdict()
    # Check for labeled reference range (e.g., "ref: 150-250" or "ref: < 100")
    if groups.get("ref_range"):
        return groups["ref_range"].strip()
    # Check for min-max range (e.g., "4.0-10.0")
    if groups.get("ref_min") and groups.get("ref_max"):
        return f"{groups['ref_min'].strip()}-{groups['ref_max'].strip()}"
    return ""


def _strip_reference_segment(line: str) -> str:
    trimmed = re.sub(r"\(([^)]*(?:ref|vr)[^)]*)\)", "", line, flags=re.IGNORECASE)
    trimmed = re.sub(r"\[([^\]]*(?:ref|vr)[^\]]*)\]", "", trimmed, flags=re.IGNORECASE)
    marker = re.search(r"(?:ref|vr|refer(?:encia)?|valor(?:es)? de ref)[:\s]", trimmed, re.IGNORECASE)
    if marker:
        trimmed = trimmed[:marker.start()]
    return trimmed.strip()


def _clean_test_name(name: str) -> str:
    cleaned = name.strip()
    cleaned = re.sub(r"^\d+\s+", "", cleaned)
    cleaned = cleaned.rstrip(":-–—")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _extract_value_and_unit(text: str) -> tuple[str, str]:
    match = VALUE_TOKEN_RE.search(text)
    if not match:
        return "", ""
    value = match.group(0).strip().replace(" ", "")
    unit = ""
    tail = text[match.end():].strip()
    if tail:
        unit_match = re.match(r"[A-Za-z/%\^0-9µμ]+", tail)
        if unit_match:
            candidate = unit_match.group(0)
            if candidate.upper() not in {"H", "L"}:
                unit = candidate
    return value, unit


def _parse_columnar_result(line: str) -> Dict[str, Any] | None:
    columns = [c.strip() for c in re.split(r"\s{2,}", line) if c and c.strip()]
    if len(columns) < 2:
        return None
    name = _clean_test_name(columns[0])
    if not name:
        return None
    value_idx = None
    for idx in range(1, len(columns)):
        if VALUE_TOKEN_RE.search(columns[idx]):
            value_idx = idx
            break
    if value_idx is None:
        return None
    value, unit = _extract_value_and_unit(columns[value_idx])
    if not value:
        return None
    reference = ""
    if value_idx + 1 < len(columns):
        for col in columns[value_idx + 1:]:
            if not unit and re.search(r"[A-Za-z/%\^]", col) and not re.search(r"\d", col):
                unit = col.strip()
                continue
            if not reference and re.search(r"\d", col):
                reference = col.strip()
    if not reference:
        reference = _extract_reference(line)
    return {
        "nome": name,
        "valor": value,
        "unidade": unit,
        "referencia": reference,
        "raw_line": line,
    }


def _clean_lines(raw_text: str) -> List[str]:
    lines = []
    for line in raw_text.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        lines.append(cleaned)
    return lines


def _truncate_lines(lines: List[str], max_len: int) -> List[str]:
    if not max_len:
        return lines
    trimmed = []
    for line in lines:
        if len(line) > max_len:
            trimmed.append(line[:max_len].rstrip())
        else:
            trimmed.append(line)
    return trimmed


def _extract_key_lines(raw_text: str) -> Dict[str, List[str]]:
    lines = _clean_lines(raw_text)
    patient_lines: List[str] = []
    result_lines: List[str] = []
    
    for line in lines:
        lower = line.lower()
        
        # Skip metadata/header lines
        if SKIP_LINE_RE.search(lower):
            continue
        
        # Extract patient info
        patient_fields = _extract_patient_fields_from_line(line)
        if patient_fields:
            patient_lines.append(line)
            # Don't continue - some lines have both patient info and result data
        
        # Enhanced detection: look for lines with numbers (values)
        has_digit = any(char.isdigit() for char in line)
        if not has_digit:
            continue
            
        # Strong indicators this is a result line
        has_result_hint = any(hint in lower for hint in RESULT_HINTS)
        has_separator = ":" in line or "-" in line or "–" in line
        
        # Check for common exam name patterns
        has_exam_pattern = bool(re.search(
            r"\b(hemoglobina|glicose|colesterol|triglicerídeos|creatinina|ureia|"
            r"ácido úrico|tsh|t3|t4|hemácias|leucócitos|plaquetas|vitamina|"
            r"ferro|ferritina|sódio|potássio|cálcio|magnésio|fósforo|"
            r"bilirrubina|tgo|tgp|ggt|fosfatase|proteína|albumina|globulina|"
            r"ldh|cpk|amilase|lipase|psa|hba1c|pcr|vhs|hemograma|"
            r"urina|fezes|glicemia|insulina|cortisol|prolactina|"
            r"testosterona|estradiol|progesterona|fsh|lh)\b",
            lower
        ))
        
        # Include if it matches strong patterns
        if has_result_hint or has_exam_pattern:
            result_lines.append(line)
            continue
        
        if has_separator:
            # Check this is not a date/time separator
            if not re.search(r"\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}", line):
                result_lines.append(line)
                continue
        
        # Include numeric lines with letters (may be test results)
        has_letters = any(char.isalpha() for char in line)
        value_tokens = VALUE_TOKEN_RE.findall(line)
        if has_letters and value_tokens:
            # Exclude common non-result lines
            skip_keywords = [
                "página", "total de", "análise", "data:", "hora:", 
                "solicitação", "laboratório", "laudo", "emissão",
                "coleta", "impressão", "material", "método"
            ]
            if not any(x in lower for x in skip_keywords):
                # Prefer lines with more than one numeric token (often columnar results)
                if len(value_tokens) >= 2 or has_result_hint or has_separator:
                    result_lines.append(line)
                elif len(line) > 10 and len(line) < 150:  # Reasonable line length for results
                    result_lines.append(line)
    
    return {"patient_lines": patient_lines, "result_lines": result_lines}


def _parse_patient_info(lines: List[str]) -> Dict[str, Any]:
    patient: Dict[str, Any] = {}
    for line in lines:
        extracted = _extract_patient_fields_from_line(line)
        for key, value in extracted.items():
            if key not in patient and value:
                patient[key] = value
    return patient


def _parse_result_lines(lines: List[str]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []

    for line in lines:
        added = False
        
        # Skip lines that are clearly not results
        lower = line.lower()
        if SKIP_LINE_RE.search(lower):
            continue
        
        # Try the main regex pattern first
        match = RESULT_LINE_RE.match(line)
        if match:
            data = match.groupdict()
            name = _clean_test_name((data.get("name") or "").strip())
            if not name or name.lower() in SKIP_RESULT_NAMES:
                pass  # Try other patterns
            else:
                results.append({
                    "nome": name,
                    "valor": (data.get("value") or "").strip().replace(" ", ""),
                    "unidade": (data.get("unit") or "").strip(),
                    "referencia": (data.get("ref") or "").strip() or _extract_reference(line),
                    "raw_line": line,
                })
                continue

        # Try flexible pattern
        flex_match = RESULT_FLEXIBLE_RE.search(line)
        if flex_match:
            data = flex_match.groupdict()
            name = _clean_test_name((data.get("name") or "").strip())
            if name and name.lower() not in SKIP_RESULT_NAMES:
                results.append({
                    "nome": name,
                    "valor": (data.get("value") or "").strip().replace(" ", ""),
                    "unidade": (data.get("unit") or "").strip(),
                    "referencia": (data.get("ref") or "").strip() or _extract_reference(line),
                    "raw_line": line,
                })
                continue
        
        # Try columnar pattern
        col_match = COLUMNAR_RE.match(line)
        if col_match:
            data = col_match.groupdict()
            name = _clean_test_name((data.get("name") or "").strip())
            if name and name.lower() not in SKIP_RESULT_NAMES:
                results.append({
                    "nome": name,
                    "valor": (data.get("value") or "").strip().replace(" ", ""),
                    "unidade": (data.get("unit") or "").strip(),
                    "referencia": (data.get("ref") or "").strip() or _extract_reference(line),
                    "raw_line": line,
                })
                continue

        # Try fixed-width column formats (common in lab tables)
        columnar = _parse_columnar_result(line)
        if columnar:
            results.append(columnar)
            continue

        reference = _extract_reference(line)
        clean_line = _strip_reference_segment(line)

        # Fallback: try to extract from space-separated or comma-separated values
        # Handle cases like: "Hemoglobina 14.5 g/dL ref: 12-16"
        tokens = clean_line.split()

        for idx, token in enumerate(tokens):
            # Look for numeric tokens (potential values)
            if VALUE_TOKEN_RE.fullmatch(token):
                name = " ".join(tokens[:idx]).strip()
                value = token.replace(" ", "")

                # Try to get unit (next token if it's not a number)
                unit = ""
                ref = reference

                if idx + 1 < len(tokens):
                    next_token = tokens[idx + 1]
                    # Check if it looks like a unit
                    if not VALUE_TOKEN_RE.match(next_token) and not any(x in next_token.lower() for x in ["ref", "vr", "refer"]):
                        unit = next_token
                        # Everything after is potential reference
                        if idx + 2 < len(tokens):
                            ref = " ".join(tokens[idx + 2:])
                    else:
                        # Next token is also numeric or a reference marker
                        ref = " ".join(tokens[idx + 1:])
                
                name = _clean_test_name(name)
                if name and name.lower() not in SKIP_RESULT_NAMES:
                    results.append({
                        "nome": name,
                        "valor": value,
                        "unidade": unit,
                        "referencia": ref,
                        "raw_line": line,
                    })
                    added = True
                    break
        if added:
            continue

        # Last resort: extract value by scanning the cleaned line
        value, unit = _extract_value_and_unit(clean_line)
        if value:
            name = _clean_test_name(clean_line[:clean_line.find(value)] if value in clean_line else clean_line)
            if name and name.lower() not in SKIP_RESULT_NAMES:
                results.append({
                    "nome": name,
                    "valor": value,
                    "unidade": unit,
                    "referencia": reference,
                    "raw_line": line,
                })

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
    min_results = int(os.getenv("EXAM_ANALYSIS_MIN_RESULTS", "8"))
    ocr_ms = 0
    ocr_pages = 0
    pipeline_result = None

    min_chars = int(os.getenv("EXAM_ANALYSIS_OCR_MIN_CHARS", "200"))
    needs_ocr = require_ocr or len(raw_text) < min_chars
    if needs_ocr:
        try:
            from pdf_pipeline.structured_extractor import run_pipeline

            ocr_start = time.perf_counter()
            pipeline = run_pipeline(file_bytes, references_path, require_ocr=True)
            pipeline_result = pipeline
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

    pipeline_always = str(os.getenv("EXAM_ANALYSIS_PIPELINE_ALWAYS", "")).lower() in {"1", "true", "yes", "on"}
    if not pipeline_result and (pipeline_always or len(lab_results) < min_results):
        try:
            from pdf_pipeline.structured_extractor import run_pipeline

            pipeline_result = run_pipeline(file_bytes, references_path, require_ocr=False)
        except Exception:
            pipeline_result = None

    if pipeline_result:
        pipeline_patient = pipeline_result.patient_data or {}
        patient_map = {
            "name": "nome",
            "gender": "sexo",
            "birth_date": "data_nascimento",
            "phone": "telefone",
            "cpf": "cpf",
        }
        for source_key, target_key in patient_map.items():
            if not patient.get(target_key) and pipeline_patient.get(source_key):
                patient[target_key] = pipeline_patient.get(source_key)

        pipeline_results = []
        for item in pipeline_result.lab_results or []:
            name = item.get("name") or item.get("nome") or item.get("test")
            if not isinstance(name, str) or not name.strip():
                continue
            pipeline_results.append({
                "nome": name.strip(),
                "valor": item.get("value") if "value" in item else item.get("valor"),
                "unidade": item.get("unit") or item.get("unidade") or "",
                "referencia": item.get("reference") or item.get("referencia") or "",
                "raw_line": item.get("raw_line") or "[PIPELINE]",
            })
        if pipeline_results:
            existing_names = {r.get("nome", "").lower().strip() for r in lab_results}
            for item in pipeline_results:
                key = item.get("nome", "").lower().strip()
                if key and key not in existing_names:
                    lab_results.append(item)
                    existing_names.add(key)

    references_raw = _load_reference_payload(references_path)
    full_lines = _clean_lines(raw_text)
    if full_lines and any(not patient.get(key) for key in ("nome", "data_nascimento", "cpf", "sexo", "telefone")):
        try:
            from prescription import extract_patient_info  # type: ignore
        except Exception:
            extract_patient_info = None  # type: ignore
        if extract_patient_info:
            try:
                name, gender, _age, cpf, phone, _doctor, birth_date = extract_patient_info(full_lines)
            except Exception:
                name = gender = cpf = phone = birth_date = ""
            if name and not patient.get("nome"):
                patient["nome"] = name
            if birth_date and not patient.get("data_nascimento"):
                patient["data_nascimento"] = birth_date
            if cpf and not patient.get("cpf"):
                patient["cpf"] = cpf
            if phone and not patient.get("telefone"):
                patient["telefone"] = phone
            if gender and not patient.get("sexo"):
                patient["sexo"] = gender
    enable_reference_scan = str(os.getenv("EXAM_ANALYSIS_REFERENCE_SCAN", "1")).lower() in {"1", "true", "yes", "on"}
    reference_scan_results: list[dict[str, Any]] = []
    if enable_reference_scan and isinstance(references_raw, dict) and full_lines:
        try:
            from prescription import scan_results  # type: ignore
        except Exception:
            scan_results = None  # type: ignore
        if scan_results:
            gender_hint = patient.get("sexo") or ""
            try:
                from prescription import _normalize_patient_gender  # type: ignore
            except Exception:
                _normalize_patient_gender = None  # type: ignore
            if _normalize_patient_gender and gender_hint:
                try:
                    gender_hint = _normalize_patient_gender(gender_hint) or gender_hint
                except Exception:
                    pass
            scanned = scan_results(full_lines, references_raw, gender_hint or "F")
            if isinstance(scanned, dict):
                for test_name, info in scanned.items():
                    if not isinstance(info, dict):
                        continue
                    value = info.get("value")
                    if value is None:
                        continue
                    reference_scan_results.append({
                        "nome": test_name,
                        "valor": value,
                        "unidade": "",
                        "referencia": info.get("ideal") or "",
                        "raw_line": info.get("line") or "[REF_SCAN]",
                    })

    if reference_scan_results:
        lab_results = reference_scan_results

    if len(lab_results) > max_results:
        lab_results = lab_results[:max_results]

    merged_lines = (key_lines.get("patient_lines") or []) + (key_lines.get("result_lines") or [])
    max_lines = int(os.getenv("EXAM_ANALYSIS_MAX_LINES", "200"))
    max_excerpt = int(os.getenv("EXAM_ANALYSIS_MAX_EXCERPT_CHARS", "12000"))
    max_line_len = int(os.getenv("EXAM_ANALYSIS_MAX_LINE_LEN", "240"))
    return {
        "patient": patient,
        "lab_results": lab_results,
        "suggestions": [],
        "key_lines": _truncate_lines(merged_lines[:max_lines], max_line_len),
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

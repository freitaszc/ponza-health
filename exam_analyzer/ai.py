"""AI helpers responsible for building the prescription prompt."""
from __future__ import annotations

import ast
import json
import os
import re
import time
import unicodedata
from difflib import get_close_matches
from pathlib import Path
from typing import Any, Dict, Optional

import requests

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - fallback when package missing
    load_dotenv = None  # type: ignore

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional dependency
    OpenAI = None  # type: ignore

if load_dotenv:
    BASE_DIR = Path(__file__).resolve().parent
    CANDIDATES = [
        BASE_DIR / ".env",
        BASE_DIR.parent / ".env",
    ]
    loaded = False
    for env_path in CANDIDATES:
        if env_path.exists():
            load_dotenv(dotenv_path=str(env_path), override=False)
            loaded = True
    if not loaded:
        load_dotenv(override=False)

OPENAI_API_URL = os.getenv("OPENAI_API_URL", "https://api.openai.com/v1/chat/completions")
DEFAULT_MODEL = "gpt-4.1-mini"
DEFAULT_FALLBACK_MODEL = "gpt-4o-mini"
OPENAI_MODEL = os.getenv("EXAM_AI_MODEL", os.getenv("OPENAI_MODEL", DEFAULT_MODEL))
FAST_MODEL = os.getenv("EXAM_AI_MODEL_FAST", OPENAI_MODEL)
FALLBACK_MODEL = os.getenv("EXAM_AI_MODEL_FALLBACK", DEFAULT_FALLBACK_MODEL)
AI_TIMEOUT = int(os.getenv("EXAM_AI_TIMEOUT", os.getenv("AI_HTTP_TIMEOUT", "45")))
MAX_TEXT = int(os.getenv("EXAM_ANALYSIS_MAX_CHARS", "20000"))
MAX_OUTPUT_TOKENS = int(os.getenv("EXAM_AI_MAX_OUTPUT_TOKENS", "1400"))
MIN_EXAMS_FOR_CONFIDENCE = int(os.getenv("EXAM_AI_MIN_EXAMS", "2"))
MAX_KEY_LINES = int(os.getenv("EXAM_AI_MAX_KEY_LINES", "200"))
FORCE_JSON_RESPONSE = str(os.getenv("EXAM_AI_FORCE_JSON", "1")).lower() in {"1", "true", "yes", "on"}

SYSTEM_PROMPT = (
    "Voce e Ponza RX, uma medica especialista em exames laboratoriais com vasta experiencia em analise de laudos. "
    "Sua tarefa e interpretar os dados de exames e gerar um resumo clinico preciso.\n\n"
    "REGRAS ESSENCIAIS:\n"
    "1. EXTRAIA CORRETAMENTE as informacoes do paciente (nome, CPF, sexo, data de nascimento, telefone) dos dados fornecidos.\n"
    "2. Para cada exame, CLASSIFIQUE o status como 'baixo', 'alto', 'normal' ou 'indefinido' comparando o valor com a referencia.\n"
    "3. O resumo_clinico deve destacar APENAS valores fora da faixa de referencia (altos ou baixos) em ate 3 linhas.\n"
    "4. Se TODOS os valores estiverem normais, use: 'Todos os exames dentro dos valores de referencia. Sem alteracoes significativas.'\n"
    "5. NUNCA invente dados. Se um campo nao estiver disponivel, deixe vazio.\n"
    "6. Responda EXCLUSIVAMENTE com JSON valido, sem texto fora dele.\n"
    "7. Se nao conseguir processar, retorne JSON minimo valido com os campos vazios."
)

OUTPUT_SPEC = {
    "paciente": {
        "nome": "",
        "data_nascimento": "",
        "cpf": "",
        "sexo": "",
        "telefone": "",
    },
    "exames": [
        {
            "nome": "",
            "valor": "",
            "unidade": "",
            "referencia": "",
            "status": "",
            "observacao": "",
        }
    ],
    "resumo_clinico": "",
    "prescricao": [],
    "orientações": [],
    "alertas": [],
}

# Extended output spec for comparison analysis
OUTPUT_SPEC_COMPARISON = {
    **OUTPUT_SPEC,
    "comparacao_exames": [
        {
            "nome": "",
            "valor_atual": "",
            "valor_anterior": "",
            "tendencia": "",  # "melhorou", "piorou", "estavel"
            "observacao": "",
        }
    ],
    "evolucao_clinica": "",
}


def _build_analysis_prompt(payload: Dict[str, Any], previous_results: Dict[str, Any] | None = None) -> str:
    patient = payload.get("patient") or {}
    lab_results = payload.get("lab_results") or []
    key_lines = payload.get("key_lines") or []
    raw_excerpt = payload.get("raw_excerpt") or ""
    ref_map = _reference_name_map(payload)
    allowed_exams = sorted({name for name in ref_map.values()}) if ref_map else []
    if ref_map:
        lab_results = _canonicalize_lab_results(lab_results, ref_map)
    if len(key_lines) > MAX_KEY_LINES:
        key_lines = key_lines[:MAX_KEY_LINES]
    input_payload = {
        "patient": patient,
        "lab_results": lab_results,
        "key_lines": key_lines,
    }
    if allowed_exams:
        input_payload["allowed_exams"] = allowed_exams
    if raw_excerpt:
        input_payload["raw_excerpt"] = raw_excerpt[:MAX_TEXT]
    
    # Add previous results for comparison if available
    if previous_results:
        input_payload["exames_anteriores"] = previous_results.get("exames") or []
        input_payload["resumo_anterior"] = previous_results.get("resumo_clinico") or ""
    
    schema = json.dumps(OUTPUT_SPEC_COMPARISON if previous_results else OUTPUT_SPEC, ensure_ascii=False, indent=2)
    input_json = json.dumps(input_payload, ensure_ascii=False, indent=2)
    
    base_instructions = (
        "Dados extraidos do laudo laboratorial:\n"
        f"{input_json}\n\n"
        "INSTRUCOES DETALHADAS:\n"
        "1. PACIENTE: Extraia os dados do paciente de 'patient' e 'key_lines'. "
        "Procure por padroes como 'Nome:', 'Paciente:', 'CPF:', 'Sexo:', 'Nascimento:', etc.\n"
        "2. EXAMES: Use os dados de 'lab_results'. Para cada exame:\n"
        "   - 'nome': use EXATAMENTE o nome de 'allowed_exams' se disponivel\n"
        "   - 'valor': o valor numerico encontrado\n"
        "   - 'unidade': a unidade de medida (g/dL, mg/dL, etc.)\n"
        "   - 'referencia': faixa de referencia indicada\n"
        "   - 'status': compare valor com referencia -> 'baixo', 'alto', 'normal' ou 'indefinido'\n"
        "   - 'observacao': breve (max 12 palavras) apenas se relevante\n"
        "3. NAO inclua cabecalhos, titulos ou metadados como exames.\n"
        "4. Para hemograma: separe valores percentuais (%) e absolutos (/mm3) em registros diferentes.\n"
        "5. RESUMO CLINICO: destaque APENAS achados anormais (status 'baixo' ou 'alto').\n"
        "   - Se todos normais: 'Todos os exames dentro dos valores de referencia.'\n"
        "   - Se houver alteracoes: liste-as de forma objetiva em ate 3 linhas.\n"
        "6. PRESCRICAO/ORIENTACOES: apenas se houver alteracoes claras. Caso contrario, deixe listas vazias.\n"
        "7. ALERTAS: apenas para valores criticamente alterados que necessitem atencao imediata.\n"
    )
    
    if previous_results:
        comparison_instructions = (
            "\n8. COMPARACAO COM EXAMES ANTERIORES:\n"
            "   - Voce recebeu 'exames_anteriores' e 'resumo_anterior' do ultimo exame do paciente.\n"
            "   - Para cada exame presente em ambos, preencha 'comparacao_exames' com:\n"
            "     - 'valor_atual': valor do exame atual\n"
            "     - 'valor_anterior': valor do exame anterior\n"
            "     - 'tendencia': 'melhorou' (saiu de alterado para normal ou valor mais proximo do ideal), "
            "'piorou' (saiu de normal para alterado ou valor mais distante do ideal), 'estavel'\n"
            "     - 'observacao': breve comentario sobre a evolucao\n"
            "   - 'evolucao_clinica': resumo da evolucao comparando os dois exames (max 3 linhas).\n"
        )
        base_instructions += comparison_instructions
    
    base_instructions += (
        "\nREGRAS CRITICAS:\n"
        "- Responda EXCLUSIVAMENTE com JSON valido seguindo o schema abaixo.\n"
        "- NAO adicione texto antes ou depois do JSON.\n"
        "- Se falhar, retorne JSON valido com campos vazios.\n"
        f"\nSCHEMA OBRIGATORIO:\n{schema}\n"
        "\nRESPONDA APENAS COM JSON:"
    )
    
    return base_instructions


def _normalize_exam_name(value: str) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", value)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _limit_summary_lines(text: str, max_lines: int = 3) -> str:
    if not text:
        return ""
    lines = [line.strip() for line in re.split(r"\r?\n", text) if line.strip()]
    if not lines:
        return ""
    if len(lines) <= max_lines:
        return "\n".join(lines)
    return "\n".join(lines[:max_lines])


def _reference_name_map(payload: Dict[str, Any]) -> dict[str, str]:
    table = payload.get("reference_table")
    if not isinstance(table, dict):
        return {}
    mapping: dict[str, str] = {}
    for name, info in table.items():
        if not isinstance(name, str):
            continue
        norm = _normalize_exam_name(name)
        if norm:
            mapping.setdefault(norm, name)
        if isinstance(info, dict):
            synonyms = info.get("synonyms") or []
            if isinstance(synonyms, list):
                for raw in synonyms:
                    if not isinstance(raw, str):
                        continue
                    syn_norm = _normalize_exam_name(raw)
                    if syn_norm:
                        mapping.setdefault(syn_norm, name)
    return mapping


def _match_reference_name(name: str, ref_map: dict[str, str]) -> str | None:
    if not name or not ref_map:
        return None
    if not re.search(r"[A-Za-zÁ-ÿ]", name):
        return None
    norm = _normalize_exam_name(name)
    if not norm or len(norm) < 3:
        return None
    if norm in ref_map:
        return ref_map[norm]
    matches = get_close_matches(norm, ref_map.keys(), n=1, cutoff=0.84)
    if matches:
        return ref_map[matches[0]]
    return None


def _lab_item_score(item: dict[str, Any]) -> float:
    score = 0.0
    if item.get("valor") not in (None, "", "—"):
        score += 2.0
    if item.get("unidade"):
        score += 1.0
    if item.get("referencia"):
        score += 1.0
    if item.get("raw_line"):
        score += 0.5
    return score


def _canonicalize_lab_results(
    lab_results: list[Any],
    ref_map: dict[str, str],
) -> list[dict[str, Any]]:
    if not ref_map:
        return [item for item in lab_results if isinstance(item, dict)]
    best: dict[str, dict[str, Any]] = {}
    for item in lab_results:
        if not isinstance(item, dict):
            continue
        raw_name = item.get("nome") or item.get("name") or item.get("test")
        if not isinstance(raw_name, str):
            continue
        canonical = _match_reference_name(raw_name, ref_map)
        if not canonical:
            continue
        normalized_key = _normalize_exam_name(canonical) or canonical
        candidate = dict(item)
        candidate["nome"] = canonical
        if normalized_key not in best or _lab_item_score(candidate) > _lab_item_score(best[normalized_key]):
            best[normalized_key] = candidate
    return [best[key] for key in sorted(best.keys())]


def _extract_json(content: str) -> Optional[Dict[str, Any]]:
    """Extract JSON from various formats, tolerating common AI response variations."""
    text = content.strip()
    
    # Remove markdown code blocks
    if text.startswith("```"):
        text = text.strip("`").strip()
        # Remove language identifier (e.g., "json")
        if text.startswith(("json", "JSON", "Json")):
            text = text.split("\n", 1)[1] if "\n" in text else text[4:]
    
    text = text.strip()
    
    # Try direct JSON parsing first
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return {"exames": parsed}
        if isinstance(parsed, dict):
            return parsed
        return None
    except json.JSONDecodeError:
        pass

    # Try to extract the first balanced JSON object/array
    balanced = _extract_balanced_json(text)
    if balanced:
        try:
            parsed = json.loads(balanced)
            if isinstance(parsed, list):
                return {"exames": parsed}
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    
    # Try extracting JSON object from surrounding text
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            json_str = text[start:end]
            parsed = json.loads(json_str)
            if isinstance(parsed, list):
                return {"exames": parsed}
            if isinstance(parsed, dict):
                return parsed
            return None
    except (json.JSONDecodeError, ValueError):
        pass
    
    # Try extracting JSON array if it starts with [
    try:
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            json_str = text[start:end]
            # Wrap in object if needed
            parsed = json.loads(json_str)
            if isinstance(parsed, list):
                return {"exames": parsed}
            if isinstance(parsed, dict):
                return parsed
            return None
    except (json.JSONDecodeError, ValueError):
        pass

    # Try Python literal eval for single-quoted or None/True/False payloads
    try:
        parsed = ast.literal_eval(text)
        if isinstance(parsed, list):
            return {"exames": parsed}
        if isinstance(parsed, dict):
            return parsed
    except (ValueError, SyntaxError):
        pass
    
    # Last resort: try to fix common JSON issues
    try:
        # Remove trailing commas
        fixed = text.replace(",\n}", "\n}").replace(",\n]", "\n]")
        fixed = fixed.replace(",}", "}").replace(",]", "]")
        # Try again
        start = fixed.find("{")
        end = fixed.rfind("}") + 1
        if start >= 0 and end > start:
            json_str = fixed[start:end]
            parsed = json.loads(json_str)
            if isinstance(parsed, list):
                return {"exames": parsed}
            if isinstance(parsed, dict):
                return parsed
            return None
    except (json.JSONDecodeError, ValueError):
        pass
    
    return None


def _extract_balanced_json(text: str) -> str | None:
    stack = []
    start_idx = None
    in_string = False
    escape = False
    for idx, ch in enumerate(text):
        if ch == '"' and not escape:
            in_string = not in_string
        if in_string:
            escape = (ch == "\\") and not escape
            continue
        escape = (ch == "\\") and not escape
        if ch in "{[":
            if start_idx is None:
                start_idx = idx
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if stack and ch == stack[-1]:
                stack.pop()
                if not stack and start_idx is not None:
                    return text[start_idx: idx + 1]
            else:
                stack = []
                start_idx = None
    return None


def _normalize_analysis_payload(data: Any, payload: Dict[str, Any]) -> tuple[Dict[str, Any], bool]:
    if not isinstance(data, dict):
        if isinstance(data, list):
            data = {"exames": data}
        else:
            return _build_minimal_response(payload), True

    paciente = data.get("paciente")
    if not isinstance(paciente, dict):
        paciente = {}
    if not paciente and isinstance(data.get("patient"), dict):
        paciente = data.get("patient") or {}

    exames_raw = data.get("exames")
    if exames_raw is None:
        exames_raw = data.get("exams")
    if not isinstance(exames_raw, list):
        exames_raw = []

    exames: list[dict[str, Any]] = []
    for item in exames_raw:
        if isinstance(item, dict):
            normalized = dict(item)
        elif isinstance(item, str):
            normalized = {"nome": item}
        else:
            continue
        if "valor" not in normalized and "value" in normalized:
            normalized["valor"] = normalized.get("value")
        if "unidade" not in normalized and "unit" in normalized:
            normalized["unidade"] = normalized.get("unit")
        if "referencia" not in normalized and "reference" in normalized:
            normalized["referencia"] = normalized.get("reference")
        if "observacao" not in normalized and "obs" in normalized:
            normalized["observacao"] = normalized.get("obs")
        exames.append(normalized)

    resumo = data.get("resumo_clinico")
    if resumo is None:
        resumo = data.get("summary") or data.get("resumo")
    resumo_clinico = resumo if isinstance(resumo, str) else ""
    resumo_clinico = _limit_summary_lines(resumo_clinico, max_lines=3)

    def _ensure_list(value: Any) -> list:
        return value if isinstance(value, list) else []

    ref_map = _reference_name_map(payload)
    if ref_map and exames:
        filtered: list[dict[str, Any]] = []
        for item in exames:
            name = item.get("nome")
            if not isinstance(name, str):
                continue
            canonical = _match_reference_name(name, ref_map)
            if not canonical:
                continue
            normalized = dict(item)
            normalized["nome"] = canonical
            filtered.append(normalized)
        exames = _canonicalize_lab_results(filtered, ref_map)

    data["paciente"] = paciente
    data["exames"] = exames
    data["resumo_clinico"] = resumo_clinico
    data["prescricao"] = _ensure_list(data.get("prescricao") or data.get("prescriptions"))
    if "orientações" in data:
        data["orientações"] = _ensure_list(data.get("orientações"))
    else:
        data["orientações"] = _ensure_list(data.get("orientacoes") or data.get("orientations"))
    data["alertas"] = _ensure_list(data.get("alertas") or data.get("alerts"))
    return data, False


def _build_minimal_response(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Build a minimal valid response when IA fails to provide valid JSON."""
    patient = payload.get("patient") or {}
    lab_results = payload.get("lab_results") or []
    ref_map = _reference_name_map(payload)
    if ref_map:
        lab_results = _canonicalize_lab_results(lab_results, ref_map)
    
    # Create minimal valid structure
    exames = []
    for result in lab_results:
        exames.append({
            "nome": result.get("nome", ""),
            "valor": result.get("valor", ""),
            "unidade": result.get("unidade", ""),
            "referencia": result.get("referencia", ""),
            "status": "indefinido",
            "observacao": "",
        })
    
    return {
        "paciente": {
            "nome": patient.get("nome", ""),
            "data_nascimento": patient.get("data_nascimento", ""),
            "cpf": patient.get("cpf", ""),
            "sexo": patient.get("sexo", ""),
            "telefone": patient.get("telefone", ""),
        },
        "exames": exames,
        "resumo_clinico": "Sem observacoes registradas.",
        "prescricao": [],
        "orientações": [],
        "alertas": [],
    }


def _supports_json_response(model: str) -> bool:
    if not model:
        return False
    normalized = model.lower()
    return any(tag in normalized for tag in ("gpt-4o", "gpt-4.1", "o1", "o3"))


def _analysis_needs_fallback(data: Dict[str, Any] | None, payload: Dict[str, Any]) -> bool:
    """Check if analysis result is incomplete and needs fallback."""
    if not data or not isinstance(data, dict):
        return True
    
    # Check if we have exames field
    exams = data.get("exames") or []
    if not isinstance(exams, list):
        return True
    if not exams:
        return True
    
    # If original payload has results, check if we got reasonable coverage
    payload_results = payload.get("lab_results") or []
    if payload_results:
        # Need at least 1/3 of original results or minimum 2
        min_expected = max(2, len(payload_results) // 3)
        if len(exams) < min_expected:
            return True
    
    # Check if we have basic patient info (at least data extraction worked)
    patient_data = data.get("paciente") or {}
    if not any(patient_data.values()):
        # If no patient data but we have exams, it's still acceptable
        return len(exams) < (MIN_EXAMS_FOR_CONFIDENCE or 1)
    
    return False


def generate_ai_analysis(
    payload: Dict[str, Any],
    *,
    timings: Dict[str, Any] | None = None,
    previous_results: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Generate AI analysis for lab results.
    
    Args:
        payload: Extracted data from the PDF
        timings: Optional dict to track timing metrics
        previous_results: Optional dict with previous exam results for comparison
            Should contain 'exames' list and 'resumo_clinico' string
    
    Returns:
        Dict with analysis results including comparison if previous_results provided
    """
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return {
            "ok": True,
            "content": "",
            "analysis": _build_minimal_response(payload),
            "error": "OPENAI_API_KEY não configurada (verifique o .env ou a variavel de ambiente).",
            "details": None,
            "fallback": True,
        }
    project = os.getenv("OPENAI_PROJECT")
    organization = os.getenv("OPENAI_ORGANIZATION") or os.getenv("OPENAI_ORG")
    user_prompt = _build_analysis_prompt(payload, previous_results=previous_results)
    timings = timings or {}

    def _call_with_model(model: str) -> Dict[str, Any]:
        sdk_error: Exception | None = None
        call_start = time.perf_counter()
        if OpenAI is not None:
            try:
                client = OpenAI(
                    api_key=api_key,
                    organization=organization or None,
                    project=project or None,
                )
                completion_kwargs = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.2,
                    "top_p": 0.9,
                    "max_tokens": MAX_OUTPUT_TOKENS,
                }
                if FORCE_JSON_RESPONSE and _supports_json_response(model):
                    completion_kwargs["response_format"] = {"type": "json_object"}
                completion = client.chat.completions.create(  # type: ignore[union-attr]
                    **completion_kwargs
                )
                timings["openai_ms"] = round((time.perf_counter() - call_start) * 1000)
                content = completion.choices[0].message.content if completion.choices else ""
                data_raw = _extract_json(content or "")
                data, used_fallback = _normalize_analysis_payload(data_raw, payload)
                if data_raw is None:
                    used_fallback = True
                
                return {
                    "ok": True,
                    "content": content or "",
                    "analysis": data,
                    "usage": getattr(completion, "usage", None),
                    "model": getattr(completion, "model", model),
                    **({"fallback": True} if used_fallback else {}),
                }
            except Exception as exc:  # pragma: no cover - log and fallback to manual request
                sdk_error = exc
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "top_p": 0.9,
            "max_tokens": MAX_OUTPUT_TOKENS,
        }
        if FORCE_JSON_RESPONSE and _supports_json_response(model):
            body["response_format"] = {"type": "json_object"}
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if project:
            headers["OpenAI-Project"] = project
        if organization:
            headers["OpenAI-Organization"] = organization
        try:
            response = requests.post(OPENAI_API_URL, headers=headers, json=body, timeout=AI_TIMEOUT)
            response.raise_for_status()
            timings["openai_ms"] = round((time.perf_counter() - call_start) * 1000)
            data = response.json()
            content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
            parsed_raw = _extract_json(content)
            parsed, used_fallback = _normalize_analysis_payload(parsed_raw, payload)
            if parsed_raw is None:
                used_fallback = True
            
            return {
                "ok": True,
                "content": content,
                "analysis": parsed,
                "usage": data.get("usage"),
                "model": data.get("model", model),
                **({"fallback": True} if used_fallback else {}),
            }
        except requests.HTTPError as exc:
            details = exc.response.text if exc.response is not None else ""
            return {
                "ok": False,
                "content": "",
                "error": f"Falha ao consultar o modelo: {exc}",
                "details": details[:5000],
            }
        except Exception as exc:
            message = f"Falha ao consultar o modelo: {exc}"
            if sdk_error:
                message += f" (SDK: {sdk_error})"
            return {
                "ok": False,
                "content": "",
                "error": message,
                "details": None,
            }

    primary_model = FAST_MODEL
    result = _call_with_model(primary_model)
    if result.get("ok") and not _analysis_needs_fallback(result.get("analysis"), payload):
        result["timings"] = timings
        return result

    fallback_model = FALLBACK_MODEL.strip()
    if fallback_model and fallback_model != primary_model:
        retry = _call_with_model(fallback_model)
        if retry.get("ok"):
            retry["timings"] = timings
            return retry

    result["timings"] = timings
    if not result.get("ok"):
        return {
            "ok": True,
            "content": "",
            "analysis": _build_minimal_response(payload),
            "error": result.get("error") or "Falha ao consultar o modelo.",
            "details": result.get("details"),
            "fallback": True,
            "timings": timings,
        }
    return result

"""AI helpers responsible for building the prescription prompt."""
from __future__ import annotations

import json
import os
import time
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
OPENAI_MODEL = os.getenv("EXAM_AI_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
FAST_MODEL = os.getenv("EXAM_AI_MODEL_FAST", OPENAI_MODEL)
FALLBACK_MODEL = os.getenv("EXAM_AI_MODEL_FALLBACK", "")
AI_TIMEOUT = int(os.getenv("EXAM_AI_TIMEOUT", os.getenv("AI_HTTP_TIMEOUT", "45")))
MAX_TEXT = int(os.getenv("EXAM_ANALYSIS_MAX_CHARS", "20000"))
MAX_OUTPUT_TOKENS = int(os.getenv("EXAM_AI_MAX_OUTPUT_TOKENS", "900"))
MIN_EXAMS_FOR_CONFIDENCE = int(os.getenv("EXAM_AI_MIN_EXAMS", "2"))
MAX_KEY_LINES = int(os.getenv("EXAM_AI_MAX_KEY_LINES", "200"))

SYSTEM_PROMPT = (
    "Voce e Ponza RX, uma medica especialista em exames laboratoriais. "
    "Use os dados estruturados para interpretar os exames e gerar um resumo clinico. "
    "Classifique cada resultado como 'baixo', 'alto', 'normal' ou 'indefinido' quando aplicavel. "
    "Sempre responda com JSON valido (sem texto adicional)."
)

OUTPUT_SPEC = {
    "paciente": {
        "nome": "",
        "data_nascimento": "",
        "cpf": "",
        "sexo": "",
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


def _build_analysis_prompt(payload: Dict[str, Any]) -> str:
    patient = payload.get("patient") or {}
    lab_results = payload.get("lab_results") or []
    key_lines = payload.get("key_lines") or []
    raw_excerpt = payload.get("raw_excerpt") or ""
    if len(key_lines) > MAX_KEY_LINES:
        key_lines = key_lines[:MAX_KEY_LINES]
    input_payload = {
        "patient": patient,
        "lab_results": lab_results,
        "key_lines": key_lines,
    }
    if raw_excerpt:
        input_payload["raw_excerpt"] = raw_excerpt[:MAX_TEXT]
    schema = json.dumps(OUTPUT_SPEC, ensure_ascii=False, indent=2)
    input_json = json.dumps(input_payload, ensure_ascii=False, indent=2)
    return (
        "Dados extraidos do laudo (nao enviar texto bruto completo):\n"
        f"{input_json}\n"
        "Instrucoes:\n"
        "- Use os dados estruturados acima; se algo estiver faltando, consulte key_lines.\n"
        "- Se lab_results estiver incompleto, use raw_excerpt como apoio.\n"
        "- Para cada exame, capture valor, unidade e referencia indicados.\n"
        "- Quando houver valores porcentuais e absolutos, crie dois registros (ex.: neutrofilos % e /mm3).\n"
        "- Use apenas os valores fornecidos; nao invente. Se nao encontrar, deixe campo vazio.\n"
        "- Classifique status comparando com a referencia escrita.\n"
        "- Seja conciso: resumo clinico com no maximo 6 linhas e prescricoes objetivas.\n"
        "- Responda EXCLUSIVAMENTE com JSON valido seguindo o schema abaixo, sem texto fora do JSON:\n"
        f"{schema}\n"
    )


def _extract_json(content: str) -> Optional[Dict[str, Any]]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if "\n" in text:
            text = text.split("\n", 1)[1]
    text = text.strip()
    if text.startswith("json"):
        text = text[4:].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            start = text.index("{")
            end = text.rindex("}") + 1
            return json.loads(text[start:end])
        except Exception:
            return None


def _analysis_needs_fallback(data: Dict[str, Any] | None, payload: Dict[str, Any]) -> bool:
    if not data:
        return True
    exams = data.get("exames") or []
    if not exams:
        return True
    payload_results = payload.get("lab_results") or []
    if payload_results and len(exams) < MIN_EXAMS_FOR_CONFIDENCE:
        return True
    if payload_results and len(exams) < max(1, len(payload_results) // 3):
        return True
    patient_name = (payload.get("patient") or {}).get("nome")
    parsed_name = (data.get("paciente") or {}).get("nome")
    if patient_name and not parsed_name:
        return True
    return False


def generate_ai_analysis(payload: Dict[str, Any], *, timings: Dict[str, Any] | None = None) -> Dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return {
            "ok": False,
            "content": "",
            "error": "OPENAI_API_KEY não configurada (verifique o .env ou a variavel de ambiente).",
            "details": None,
        }
    project = os.getenv("OPENAI_PROJECT")
    organization = os.getenv("OPENAI_ORGANIZATION") or os.getenv("OPENAI_ORG")
    user_prompt = _build_analysis_prompt(payload)
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
                completion = client.chat.completions.create(  # type: ignore[union-attr]
                    model=model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.2,
                    top_p=0.9,
                    max_tokens=MAX_OUTPUT_TOKENS,
                )
                timings["openai_ms"] = round((time.perf_counter() - call_start) * 1000)
                content = completion.choices[0].message.content if completion.choices else ""
                data = _extract_json(content or "")
                if not data:
                    raise ValueError("Não foi possivel interpretar o JSON retornado.")
                return {
                    "ok": True,
                    "content": content or "",
                    "analysis": data,
                    "usage": getattr(completion, "usage", None),
                    "model": getattr(completion, "model", model),
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
            parsed = _extract_json(content)
            if not parsed:
                return {
                    "ok": False,
                    "content": content,
                    "error": "Falha ao interpretar o JSON retornado pela IA.",
                    "details": content[:2000],
                }
            return {
                "ok": True,
                "content": content,
                "analysis": parsed,
                "usage": data.get("usage"),
                "model": data.get("model", model),
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
    return result

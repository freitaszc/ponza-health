"""AI helpers responsible for building the prescription prompt."""
from __future__ import annotations

import json
import os
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
AI_TIMEOUT = int(os.getenv("EXAM_AI_TIMEOUT", os.getenv("AI_HTTP_TIMEOUT", "45")))
MAX_TEXT = int(os.getenv("EXAM_ANALYSIS_MAX_CHARS", "20000"))

SYSTEM_PROMPT = (
    "Voce e Ponza RX, uma medica especialista em exames laboratoriais. "
    "Leia o texto bruto do laudo e extraia cada exame com valor, unidade e faixa descrita. "
    "Classifique cada resultado como 'baixo', 'alto', 'normal' ou 'indefinido'. "
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
    raw_text = (payload.get("raw_text") or "").strip()
    truncated = raw_text[:MAX_TEXT]
    schema = json.dumps(OUTPUT_SPEC, ensure_ascii=False, indent=2)
    return (
        "Texto integral do laudo (preserve numericos exatamente):\n"
        f"```LAUDO\n{truncated}\n```\n"
        "Instrucoes:\n"
        "- Identifique paciente (nome, data de nascimento, CPF, sexo se existir).\n"
        "- Para cada exame, capture exatamente o valor, unidade e referencia indicados.\n"
        "- Quando houver valores porcentuais e absolutos, crie dois registros (ex.: neutrofilos % e /mm3).\n"
        "- Use apenas os valores do laudo; não invente. Se não encontrar, deixe campo vazio.\n"
        "- Classifique status comparando com a referencia escrita.\n"
        "- Liste as alterações relevantes no resumo clinico, proponha condutas e orientações breves.\n"
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


def generate_ai_analysis(payload: Dict[str, Any]) -> Dict[str, Any]:
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
    sdk_error: Exception | None = None
    if OpenAI is not None:
        try:
            client = OpenAI(
                api_key=api_key,
                organization=organization or None,
                project=project or None,
            )
            completion = client.chat.completions.create(  # type: ignore[union-attr]
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                top_p=0.9,
            )
            content = completion.choices[0].message.content if completion.choices else ""
            data = _extract_json(content or "")
            if not data:
                raise ValueError("Não foi possivel interpretar o JSON retornado.")
            return {
                "ok": True,
                "content": content or "",
                "analysis": data,
                "usage": getattr(completion, "usage", None),
                "model": getattr(completion, "model", OPENAI_MODEL),
            }
        except Exception as exc:  # pragma: no cover - log and fallback to manual request
            sdk_error = exc
    body = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "top_p": 0.9,
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
            "model": data.get("model", OPENAI_MODEL),
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

"""CLI helper to inspect PDF extraction and AI stages."""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path
from typing import Any

from tenacity import RetryError

BASE_PATH = Path(__file__).resolve().parents[1]
if str(BASE_PATH) not in sys.path:
    sys.path.insert(0, str(BASE_PATH))

from exam_analyzer import pdf_extractor
from exam_analyzer.ai import generate_ai_analysis
from pdf_pipeline.structured_extractor import run_pipeline  # type: ignore


def _print_header(title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def _display_exception(exc: BaseException) -> None:
    print(f"[erro] {exc.__class__.__name__}: {exc}")
    traceback.print_exception(type(exc), exc, exc.__traceback__)


def _stage_pipeline(file_bytes: bytes, require_ocr: bool) -> tuple[Any | None, str]:
    references_path = pdf_extractor._locate_references()
    _print_header("1) Pipeline estruturado")
    print(f"Referencias: {references_path}")
    try:
        result = run_pipeline(file_bytes, references_path, require_ocr=require_ocr)
        print(f"Blocos extraidos: {len(result.artifacts.blocks)}")
        print(f"Resultados estruturados: {len(result.lab_results)}")
        return result, references_path
    except RetryError as exc:
        print("[falha] Tenacity atingiu o limite de tentativas.")
        last_attempt = getattr(exc, "last_attempt", None)
        if last_attempt:
            inner = last_attempt.exception()
            if inner:
                _display_exception(inner)
        else:
            _display_exception(exc)
        return None, references_path
    except Exception as exc:
        _display_exception(exc)
        return None, references_path


def _stage_payload(file_bytes: bytes, require_ocr: bool) -> dict[str, Any] | None:
    _print_header("2) Aggregacao do payload")
    try:
        payload = pdf_extractor.extract_exam_payload(file_bytes, require_ocr=require_ocr)
        print(f"Paciente detectado: {payload.get('patient') or 'n/d'}")
        print(f"Resultados estruturados: {len(payload.get('lab_results') or [])}")
        suggestions = payload.get("suggestions") or []
        if suggestions:
            print("Sugestoes do pipeline:")
            for item in suggestions[:5]:
                print(f"- {item}")
        return payload
    except Exception as exc:
        _display_exception(exc)
        return None


def _stage_ai(payload: dict[str, Any]) -> None:
    _print_header("3) Chamada da IA")
    result = generate_ai_analysis(payload)
    if result.get("ok"):
        analysis = result.get("analysis") or {}
        print("Resumo clinico:", analysis.get("resumo_clinico", ""))
        print(f"Exames retornados: {len(analysis.get('exames') or [])}")
        paciente = analysis.get("paciente")
        if paciente:
            print("Paciente:", paciente)
    else:
        print("Falha na chamada:")
        print(result.get("error"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Debugger para o analisador de exames.")
    parser.add_argument("pdf", help="Caminho para o arquivo PDF.")
    parser.add_argument("--require-ocr", action="store_true", help="Forca OCR completo na extracao.")
    parser.add_argument("--run-ai", action="store_true", help="Executa a etapa da IA para teste.")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"Arquivo nao encontrado: {pdf_path}")
        return 1
    file_bytes = pdf_path.read_bytes()

    _stage_pipeline(file_bytes, args.require_ocr)
    payload = _stage_payload(file_bytes, args.require_ocr)
    if args.run_ai and payload:
        _stage_ai(payload)
    elif args.run_ai:
        print("Payload indisponivel; etapa de IA ignorada.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

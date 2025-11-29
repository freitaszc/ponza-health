"""Minimal Flask app that focuses on PDF analysis + AI prescription."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict

from flask import Flask, flash, render_template, request
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from exam_analyzer.ai import generate_ai_analysis
from exam_analyzer.pdf_extractor import ReferenceNotFoundError, extract_exam_payload

ALLOWED_EXTENSIONS = {"pdf"}

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = os.getenv("EXAM_ANALYZER_SECRET", "ponza-analyzer")
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB
app.config["UPLOAD_FOLDER"] = os.path.join(tempfile.gettempdir(), "ponza_exam_uploads")
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)


def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/", methods=["GET", "POST"])
def index():
    context: Dict[str, Any] = {"extraction": None, "ai_result": None, "file_name": None}
    if request.method == "POST":
        file = request.files.get("pdf_file")
        if not file or not file.filename:
            flash("Envie um arquivo PDF para analise.", "warning")
            return render_template("index.html", **context)
        if not _allowed_file(file.filename):
            flash("Formato invalido. Envie apenas arquivos .pdf.", "warning")
            return render_template("index.html", **context)
        filename = secure_filename(file.filename)
        try:
            file_bytes = file.read()
            extraction = extract_exam_payload(file_bytes, require_ocr=False)
            ai_result = generate_ai_analysis(extraction)
            context.update(
                {
                    "file_name": filename,
                    "extraction": extraction,
                    "ai_result": ai_result,
                }
            )
            if not ai_result.get("ok"):
                flash(ai_result.get("error") or "Falha ao gerar a analise inteligente.", "warning")
            else:
                analysis = ai_result.get("analysis") or {}
                extraction["patient"] = analysis.get("paciente") or {}
                extraction["lab_results"] = analysis.get("exames") or []
        except ReferenceNotFoundError as exc:
            flash(str(exc), "danger")
        except Exception as exc:
            flash(f"Erro ao processar o PDF: {exc}", "danger")
    return render_template("index.html", **context)


def create_app() -> Flask:
    """Factory para integração com outros servidores."""
    return app


if __name__ == "__main__":
    app.run(debug=True, port=int(os.getenv("PORT", "5050")))

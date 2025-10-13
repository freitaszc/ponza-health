import os
import re
import json
import requests
import pymupdf as fitz
from datetime import datetime
from typing import Optional, List
from flask import current_app, url_for
from itsdangerous import URLSafeSerializer
from difflib import get_close_matches

# ======================================================
# =============== VARIÁVEIS GLOBAIS ====================
# ======================================================

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WHATSAPP_API_URL = "https://graph.facebook.com/v18.0"
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
ADMIN_WHATSAPP = os.getenv("ADMIN_WHATSAPP", "").strip()


# ======================================================
# =============== PDF PARSING ===========================
# ======================================================

def read_pdf(file_path):
    """Lê PDF com PyMuPDF (fitz)."""
    try:
        text = ""
        with fitz.open(file_path) as doc:
            for page in doc:
                text += page.get_text("text") or ""  # type: ignore
        return [line.strip() for line in text.splitlines() if line.strip()]
    except Exception as e:
        print(f"Error reading PDF with PyMuPDF: {e}")
        return []


# ======================================================
# =============== REFERÊNCIAS JSON ======================
# ======================================================

def read_references(references_path):
    try:
        with open(references_path, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception as e:
        print(f"Error reading references: {e}")
        return None


def parse_min_max(ideal_text):
    """Interpreta faixas numéricas do campo 'ideal'."""
    try:
        ideal_text = ideal_text.strip().split("\n")[0]
        if m := re.match(r"(≥|>=|>)\s*([0-9]+(?:[.,][0-9]+)?)", ideal_text):
            return float(m.group(2).replace(",", ".")), float("inf")
        if m := re.match(r"(≤|<=|<)\s*([0-9]+(?:[.,][0-9]+)?)", ideal_text):
            return float("-inf"), float(m.group(2).replace(",", "."))
        if m := re.search(r"([0-9]+(?:[.,][0-9]+)?)\s*[-–]\s*([0-9]+(?:[.,][0-9]+)?)", ideal_text):
            return float(m.group(1).replace(",", ".")), float(m.group(2).replace(",", "."))
        if m := re.search(r"([0-9]+(?:[.,][0-9]+)?)", ideal_text):
            v = float(m.group(1).replace(",", "."))
            return v, v
        return None, None
    except:
        return None, None


# ======================================================
# =============== EXTRAÇÃO DE PACIENTE =================
# ======================================================

def extract_patient_info(lines):
    name, gender, birth_date, age, cpf, phone, doctor = "", "", "", 0, "", "", ""
    for line in lines:
        if m := re.match(r"^([A-Z\s]+)\s+(\d{2}/\d{2}/\d{4})\s+\((\d+)\s+anos\)", line):
            name = m.group(1).strip().title()
            birth_date = m.group(2)
            try:
                birth_dt = datetime.strptime(birth_date, "%d/%m/%Y")
                today = datetime.today()
                age = today.year - birth_dt.year - ((today.month, today.day) < (birth_dt.month, birth_dt.day))
            except:
                age = 0

        if cpf_match := re.search(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b", line):
            cpf = cpf_match.group()

        if "CRM-" in line:
            if doctor_match := re.search(r"([A-Z\s\.]+)\s*-\s*CRM", line):
                doctor = doctor_match.group(1).strip().title()

    gender = "M" if any(x in name.upper() for x in [" JOÃO ", " PAULO ", " LUCAS ", " GABRIEL "]) else "F"
    return name, gender, age, cpf, phone, doctor


# ======================================================
# =============== ANÁLISE DE RESULTADOS ================
# ======================================================

def scan_results(lines, references, gender):
    results = {}
    normalized_lines = [line.lower() for line in lines]

    for test_name, info in references.items():
        synonyms = [s.lower() for s in info.get("synonyms", [])] + [test_name.lower()]
        found = False

        for i, line in enumerate(normalized_lines):
            for synonym in synonyms:
                if synonym in line:
                    combined_line = lines[i] + " " + (lines[i + 1] if i + 1 < len(lines) else "")
                    if m := re.search(r"([<>]?\s*\d{1,3}(?:[.,]\d{1,3})?)", combined_line):
                        value = float(m.group(1).replace(",", ".").replace(">", "").replace("<", "").strip())
                    else:
                        value = None

                    ideal = info.get("ideal", {}).get(gender) if isinstance(info.get("ideal"), dict) else info.get("ideal")
                    min_val, max_val = parse_min_max(str(ideal))
                    meds = []
                    if value is not None and min_val is not None:
                        if value < min_val:
                            meds = info.get("medications", {}).get("low", [])
                        elif max_val is not None and value > max_val:
                            meds = info.get("medications", {}).get("high", [])

                    results[test_name] = {
                        "value": value,
                        "line": lines[i].strip(),
                        "ideal": ideal,
                        "medications": meds,
                    }
                    found = True
                    break
            if found:
                break

        if not found:
            results[test_name] = {"value": None, "line": None, "ideal": None, "medications": []}
    return results


# ======================================================
# =============== DIAGNÓSTICO ==========================
# ======================================================

def build_diagnosis_and_prescriptions(results):
    diagnosis_text = ""
    prescriptions = []
    for test, info in results.items():
        value, ideal, meds = info["value"], info["ideal"], info["medications"]
        if value is None or ideal is None:
            continue
        min_val, max_val = parse_min_max(str(ideal))
        if min_val is None or max_val is None:
            continue
        if value < min_val:
            diagnosis_text += f"{test}: valor {value} ABAIXO do valor ideal ({ideal}).\n"
            prescriptions.extend([{"test": test, **med} for med in meds])
        elif value > max_val:
            diagnosis_text += f"{test}: valor {value} ACIMA do valor ideal ({ideal}).\n"
            prescriptions.extend([{"test": test, **med} for med in meds])
        else:
            diagnosis_text += f"{test}: valor {value} está dentro do valor ideal ({ideal}).\n"

    seen = set()
    prescription_lines = []
    for med in prescriptions:
        if (key := med["nome"]) not in seen:
            seen.add(key)
            prescription_lines.append(
                f"- {med['nome']}\nPreparo: {med['preparo']}\nAplicação: {med['aplicacao']}\n"
            )
    return diagnosis_text.strip(), "\n".join(prescription_lines).strip()


# ======================================================
# =============== ANÁLISE GERAL DE PDF =================
# ======================================================

def analyze_pdf(source, references_path="json/references.json", manual=False):
    references = read_references(references_path)
    if manual:
        lines = [l.strip() for l in source.splitlines() if l.strip()]
        gender = "F"
        results = scan_results(lines, references, gender)
        diagnosis, prescriptions = build_diagnosis_and_prescriptions(results)
        return diagnosis, prescriptions, "", gender, 0, "", "", ""

    lines = read_pdf(source)
    if not lines or not references:
        return "Erro ao extrair com IA", "", "", "", 0, "", "", ""

    name, gender, age, cpf, phone, doctor = extract_patient_info(lines)
    results = scan_results(lines, references, gender)
    diagnosis, prescriptions = build_diagnosis_and_prescriptions(results)
    return diagnosis, prescriptions, name, gender, age, cpf, phone, doctor


# ======================================================
# =============== WHATSAPP HELPERS =====================
# ======================================================

def _headers() -> dict:
    if not WHATSAPP_TOKEN:
        raise RuntimeError("WHATSAPP_TOKEN not configured")
    return {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }


def _endpoint() -> str:
    if not WHATSAPP_PHONE_NUMBER_ID:
        raise RuntimeError("WHATSAPP_PHONE_NUMBER_ID not configured")
    return f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/messages"


def _post_whatsapp(payload: dict) -> Optional[str]:
    """Envia payload ao WhatsApp Cloud API."""
    try:
        resp = requests.post(_endpoint(), headers=_headers(), json=payload, timeout=30)
        if resp.status_code not in (200, 201):
            try:
                data = resp.json()
            except Exception:
                data = {"raw": resp.text}
            return f"WA API error {resp.status_code}: {data}"
        return None
    except Exception as e:
        return f"WA request failed: {e}"


def normalize_phone(msisdn: str) -> str:
    """Normaliza número para formato internacional."""
    if not msisdn:
        return msisdn
    digits = re.sub(r"\D", "", msisdn)
    if digits.startswith("55") and len(digits) in (12, 13):
        return digits
    if len(digits) == 11 and not digits.startswith("55"):
        return f"55{digits}"
    return digits


# ======================================================
# =============== ENVIO DE RELATÓRIOS ==================
# ======================================================

def send_pdf_whatsapp_template(template_name, doctor_name, patient_name, phone, patient_id):
    if not phone:
        return "Nenhum telefone informado."
    s = URLSafeSerializer(current_app.config["SECRET_KEY"])
    token = s.dumps(patient_id)
    analyzed_link = url_for("public_download", token=token, _external=True)
    payload = {
        "messaging_product": "whatsapp",
        "to": normalize_phone(phone),
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": "pt_BR"},
            "components": [{
                "type": "body",
                "parameters": [
                    {"type": "text", "text": doctor_name or "-"},
                    {"type": "text", "text": patient_name or "-"},
                    {"type": "text", "text": analyzed_link}
                ],
            }],
        },
    }
    return _post_whatsapp(payload)


def send_pdf_whatsapp_patient(patient_name, patient_phone, patient_id, clinic_phone=None):
    if not patient_phone:
        return "Nenhum telefone informado."
    s = URLSafeSerializer(current_app.config["SECRET_KEY"])
    token = s.dumps(patient_id)
    analyzed_link = url_for("public_download", token=token, _external=True)
    payload = {
        "messaging_product": "whatsapp",
        "to": normalize_phone(patient_phone),
        "type": "template",
        "template": {
            "name": "relatorio_paciente_ponza",
            "language": {"code": "pt_BR"},
            "components": [{
                "type": "body",
                "parameters": [
                    {"type": "text", "text": patient_name or "-"},
                    {"type": "text", "text": analyzed_link},
                    {"type": "text", "text": clinic_phone or "-"}
                ],
            }],
        },
    }
    return _post_whatsapp(payload)


# ======================================================
# =============== ENVIO DE COTAÇÕES ====================
# ======================================================

def send_quote_whatsapp(supplier_name, phone, quote_title, quote_items, response_url):
    if not phone:
        return f"Fornecedor '{supplier_name}' sem telefone."
    to = normalize_phone(phone)
    items_text = " | ".join(f"• {it}" for it in (quote_items or [])[:10]).strip() or "-"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": "ponzahealth_cotacao",
            "language": {"code": "pt_BR"},
            "components": [{
                "type": "body",
                "parameters": [
                    {"type": "text", "text": supplier_name or "-"},
                    {"type": "text", "text": quote_title or "-"},
                    {"type": "text", "text": items_text},
                    {"type": "text", "text": response_url or "-"}
                ],
            }],
        },
    }
    err = _post_whatsapp(payload)
    if err:
        print(f"[WA] Erro ao enviar cotação para {supplier_name}: {err}")
    return err


# ======================================================
# =============== LEMBRETES ============================
# ======================================================

def send_reminder_doctor(clinic_phone, patient_name, clinic_name, date_str, time_start, time_end):
    if not clinic_phone:
        return "Nenhum telefone da clínica informado."
    payload = {
        "messaging_product": "whatsapp",
        "to": normalize_phone(clinic_phone),
        "type": "template",
        "template": {
            "name": "appointment_scheduling",
            "language": {"code": "pt_BR"},
            "components": [{
                "type": "body",
                "parameters": [
                    {"type": "text", "text": patient_name or "-"},
                    {"type": "text", "text": clinic_name or "-"},
                    {"type": "text", "text": date_str or "-"},
                    {"type": "text", "text": time_start or "-"},
                    {"type": "text", "text": time_end or "-"},
                ],
            }],
        },
    }
    return _post_whatsapp(payload)


def send_reminder_patient(patient_phone, patient_name, clinic_name, date_str, time_start, time_end):
    if not patient_phone:
        return "Nenhum telefone informado."
    payload = {
        "messaging_product": "whatsapp",
        "to": normalize_phone(patient_phone),
        "type": "template",
        "template": {
            "name": "appointment_scheduling",
            "language": {"code": "pt_BR"},
            "components": [{
                "type": "body",
                "parameters": [
                    {"type": "text", "text": patient_name or "-"},
                    {"type": "text", "text": clinic_name or "-"},
                    {"type": "text", "text": date_str or "-"},
                    {"type": "text", "text": time_start or "-"},
                    {"type": "text", "text": time_end or "-"},
                ],
            }],
        },
    }
    return _post_whatsapp(payload)


# ======================================================
# =============== TEXTO LIVRE ==========================
# ======================================================

def send_text(to_phone, text):
    to = normalize_phone(to_phone)
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"preview_url": True, "body": text},
    }
    return _post_whatsapp(payload)

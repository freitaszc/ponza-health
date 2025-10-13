import os
import re
import json
import requests
import fitz
from datetime import datetime
from typing import Optional, List
from flask import current_app, url_for
from itsdangerous import URLSafeSerializer
from difflib import get_close_matches

# ======================================================
# =============== VARIÁVEIS GLOBAIS ====================
# ======================================================

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"

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
                text += page.get_text("text") or ""
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
    """
    Extrai informações pessoais do paciente (nome, sexo, data de nascimento, idade, CPF, médico),
    usando heurísticas locais e fallback via IA se necessário.
    """
    name, gender, birth_date, age, cpf, phone, doctor = "", "", "", 0, "", "", ""
    joined_text = "\n".join(lines)

    # 1️⃣ Nome
    patterns = [
        r"(?i)(?:paciente|cliente|nome\s*do\s*paciente|identificação|nome)\s*[:\-]?\s*([A-ZÁÉÍÓÚÂÊÔÃÕÇa-záéíóúâêôãõç\s]{3,})",
        r"(?im)^([A-ZÁÉÍÓÚÂÊÔÃÕÇa-záéíóúâêôãõç\s]{3,})\s+\d{2}[/-]\d{2}[/-]\d{4}\b",
    ]
    for p in patterns:
        if m := re.search(p, joined_text):
            name = re.sub(r"\s{2,}", " ", m.group(1)).strip().title()
            break

    # 2️⃣ Data de nascimento
    dob_patterns = [
        r"(?i)(?:nasc(?:imento)?|dn|data\s*de\s*nascimento)\s*[:\-]?\s*(\d{2}[/-]\d{2}[/-]\d{4})",
        r"(?i)\b(\d{2}[/-]\d{2}[/-]\d{4})\b\s*(?:\(nas[cç]?\))?",
    ]
    for p in dob_patterns:
        if m := re.search(p, joined_text):
            birth_date = m.group(1)
            break

    # 3️⃣ CPF
    if cpf_match := re.search(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b", joined_text):
        cpf = cpf_match.group()

    # 4️⃣ Idade (cálculo via data de nascimento)
    if not birth_date:
        if age_match := re.search(r"(\d{1,3})\s*(?:anos|anos de idade)", joined_text, re.I):
            age = int(age_match.group(1))
    else:
        try:
            dob = datetime.strptime(birth_date, "%d/%m/%Y")
            today = datetime.today()
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        except Exception:
            age = 0

    # 5️⃣ Sexo
    if re.search(r"\bmasculino\b", joined_text, re.I):
        gender = "M"
    elif re.search(r"\bfeminino\b", joined_text, re.I):
        gender = "F"

    # 6️⃣ Médico / CRM
    doctor_patterns = [
        r"(?i)(?:dr\.?|doutor|médico\s*responsável|médico)\s*[:\-]?\s*([A-ZÁÉÍÓÚÂÊÔÃÕÇa-záéíóúâêôãõç\s]{3,})",
        r"(?i)([A-ZÁÉÍÓÚÂÊÔÃÕÇa-záéíóúâêôãõç\s]{3,})\s*[-–]\s*CRM[-:\s]*\d{2,6}"
    ]
    for p in doctor_patterns:
        if m := re.search(p, joined_text):
            doctor = m.group(1).strip().title()
            break

    # 7️⃣ Fallback com IA para garantir Nome + Data de Nascimento + CRM
    if OPENAI_API_KEY:
        try:
            excerpt = "\n".join(lines[:40])
            prompt = (
                "Você é um assistente médico especializado em interpretar laudos laboratoriais em português.\n"
                "Analise o texto abaixo e extraia com precisão:\n"
                "nome completo, data de nascimento, idade, CPF, sexo, telefone, médico e CRM.\n"
                "Não invente valores. Caso o dado não esteja presente, deixe o campo vazio.\n"
                "Responda SOMENTE em JSON válido com os seguintes campos:\n"
                "{\n"
                "  'nome': '',\n"
                "  'data_nascimento': '',\n"
                "  'idade': '',\n"
                "  'cpf': '',\n"
                "  'sexo': '',\n"
                "  'telefone': '',\n"
                "  'medico': '',\n"
                "  'crm': ''\n"
                "}\n\n"
                f"TEXTO DO LAUDO:\n{excerpt}"
            )
            response = requests.post(
                OPENAI_API_URL,
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0
                },
                timeout=40,
            )
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            if match := re.search(r"\{.*\}", content, re.S):
                ai_data = json.loads(match.group(0))
                name = ai_data.get("nome", name).strip().title()
                birth_date = ai_data.get("data_nascimento", birth_date)
                cpf = ai_data.get("cpf", cpf)
                gender = ai_data.get("sexo", gender)
                age = ai_data.get("idade", age)
                phone = ai_data.get("telefone", phone)
                doctor = ai_data.get("medico", doctor).strip().title()
                crm = ai_data.get("crm", "")
                if crm and crm not in doctor:
                    doctor = f"{doctor} - CRM {crm}".strip(" -")
        except Exception as e:
            print(f"[AI patient info fallback error] {e}")

    # Sanitização
    name = re.sub(r"\s{2,}", " ", name).strip().title()
    doctor = re.sub(r"\s{2,}", " ", doctor).strip().title()
    birth_date = birth_date.replace("-", "/").strip() if birth_date else ""

    print(f"[INFO] Extracted -> Nome: {name}, Nasc: {birth_date}, CPF: {cpf}, Sexo: {gender}, Idade: {age}, Médico: {doctor}")

    return name, gender, age, cpf, phone, doctor, birth_date

# ======================================================
# =============== AI CORREÇÃO DE RESULTADOS =============
# ======================================================

def ai_refine_results(raw_text: str, initial_results: dict) -> dict:
    """Usa a IA para corrigir valores incorretos extraídos do PDF."""
    if not OPENAI_API_KEY:
        return initial_results

    # remove datas para evitar confusão
    clean_text = re.sub(r'\b\d{1,2}/\d{1,2}/\d{2,4}\b', '', raw_text)

    prompt = (
        "You are a clinical lab data parser. "
        "Given the extracted lab report text and initial JSON of test results, "
        "correct any numeric values that are wrong or mixed with dates. "
        "Ignore any date-like patterns (e.g., 12/05/2024) or numbers that are part of a date. "
        "Return only valid JSON with corrected 'value' fields.\n\n"
        f"RAW TEXT:\n{clean_text[:6000]}\n\n"
        f"INITIAL JSON:\n{json.dumps(initial_results, ensure_ascii=False, indent=2)}"
    )

    try:
        response = requests.post(
            OPENAI_API_URL,
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}], "temperature": 0},
            timeout=25,
        )
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        match = re.search(r"\{.*\}", content, re.S)
        if match:
            corrected = json.loads(match.group(0))
            if isinstance(corrected, dict):
                return corrected
    except Exception as e:
        print(f"[AI refine error] {e}")
    return initial_results

# ======================================================
# =============== AI ANÁLISE COMPLETA ==================
# ======================================================

def ai_full_analysis(file_path: str, references_path: str):
    """Análise completa via IA, comparando resultados com faixas ideais."""
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY não configurada.")

    # Lê texto do PDF
    lines = read_pdf(file_path)
    if not lines:
        raise ValueError("Falha ao ler o PDF.")
    raw_text = "\n".join(lines)
    raw_text = re.sub(r'\b\d{1,2}/\d{1,2}/\d{2,4}\b', '', raw_text)  # remove datas

    # Lê referências
    references = read_references(references_path)
    if not references:
        raise ValueError("Falha ao ler referências JSON.")

    prompt = f"""
You are a licensed medical assistant AI.
You will receive a laboratory report (Portuguese) and JSON with reference ranges.
Identify each test and numeric value.
Ignore any date-like values (e.g., 12/05/2024).
Compare results with reference ranges and produce a summary.

Output format (strict JSON):
{{
  "diagnosis": "Resumo médico em português",
  "prescription": "Lista de suplementos/recomendações"
}}

LAB REPORT:
{raw_text[:6000]}

REFERENCE VALUES JSON:
{json.dumps(references, ensure_ascii=False)[:6000]}
"""

    try:
        response = requests.post(
            OPENAI_API_URL,
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}], "temperature": 0},
            timeout=60,
        )
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        match = re.search(r"\{.*\}", content, re.S)
        if match:
            parsed = json.loads(match.group(0))
            return parsed.get("diagnosis", ""), parsed.get("prescription", "")
        raise ValueError("Falha ao interpretar resposta da IA.")
    except Exception as e:
        print(f"[AI full analysis error] {e}")
        raise

# ======================================================
# =============== ANÁLISE DE RESULTADOS ================
# ======================================================
def scan_results(lines, references, gender):
    results = {}
    normalized_lines = [line.lower() for line in lines]

    for test_name, info in references.items():
        synonyms = [s.lower() for s in info.get("synonyms", [])] + [test_name.lower()]
        best_match = None
        best_index = -1  # ← garante que seja sempre int

        for i, line in enumerate(normalized_lines):
            for synonym in synonyms:
                if synonym in line or get_close_matches(synonym, [line], cutoff=0.85):
                    best_match = line
                    best_index = i
                    break
            if best_match:
                break

        if best_index == -1:
            results[test_name] = {"value": None, "line": None, "ideal": None, "medications": []}
            continue

        combined_line = lines[best_index]
        if best_index + 1 < len(lines):
            combined_line += " " + lines[best_index + 1]

        # Ignora linhas que parecem datas
        if re.search(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", combined_line):
            results[test_name] = {"value": None, "line": combined_line, "ideal": None, "medications": []}
            continue

        m = re.search(r"([<>]?\s*\d+(?:[.,]\d{1,4})?)", combined_line)
        value = None
        if m:
            try:
                value = float(m.group(1).replace(",", ".").replace(">", "").replace("<", "").strip())
            except ValueError:
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
            "line": combined_line.strip(),
            "ideal": ideal,
            "medications": meds,
        }

    return results

# ======================================================
# =============== DIAGNÓSTICO ==========================
# ======================================================
def build_diagnosis_and_prescriptions(results):
    """
    Monta texto de diagnóstico e lista de prescrições com base nos resultados.
    Garante que medicamentos não sejam perdidos e evita sobrescritas.
    """
    diagnosis_text = []
    prescriptions = []

    for test, info in results.items():
        value, ideal, meds = info["value"], info["ideal"], info["medications"]

        if value is None or not ideal:
            continue

        min_val, max_val = parse_min_max(str(ideal))
        if min_val is None or max_val is None:
            continue

        if value < min_val:
            diagnosis_text.append(f"{test}: valor {value} ABAIXO do ideal ({ideal}).")
            prescriptions.extend([{"test": test, **med} for med in meds])
        elif value > max_val:
            diagnosis_text.append(f"{test}: valor {value} ACIMA do ideal ({ideal}).")
            prescriptions.extend([{"test": test, **med} for med in meds])
        else:
            diagnosis_text.append(f"{test}: valor {value} dentro do ideal ({ideal}).")

    # Remove duplicadas e formata
    seen = set()
    prescription_lines = []
    for med in prescriptions:
        name = med.get("nome")
        if name and name not in seen:
            seen.add(name)
            prep = med.get("preparo", "—")
            appl = med.get("aplicacao", "—")
            prescription_lines.append(f"- {name}\nPreparo: {prep}\nAplicação: {appl}\n")

    return "\n".join(diagnosis_text).strip(), "\n".join(prescription_lines).strip()

# ======================================================
# =============== ANÁLISE GERAL DE PDF =================
# ======================================================

def analyze_pdf(source, references_path="json/references.json", manual=False):
    """
    Analisa o PDF e retorna diagnóstico, prescrição e dados do paciente.
    Inclui data de nascimento detectada pelo extrator.
    """
    references = read_references(references_path)

    if manual:
        lines = [l.strip() for l in source.splitlines() if l.strip()]
        gender = "F"
        results = scan_results(lines, references, gender)
        diagnosis, prescriptions = build_diagnosis_and_prescriptions(results)
        return diagnosis, prescriptions, "", gender, 0, "", "", "", ""

    lines = read_pdf(source)
    if not lines or not references:
        return "Erro ao extrair com IA", "", "", "", 0, "", "", "", ""

    raw_text = "\n".join(lines)

    try:
        name, gender, age, cpf, phone, doctor, birth_date = extract_patient_info(lines)
    except Exception as e:
        print(f"[analyze_pdf] Erro ao extrair dados pessoais: {e}")
        name, gender, age, cpf, phone, doctor, birth_date = "", "", 0, "", "", "", ""

    # Correção de resultados via IA
    results = scan_results(lines, references, gender)
    results = ai_refine_results(raw_text, results)

    # Diagnóstico e prescrição
    diagnosis, prescriptions = build_diagnosis_and_prescriptions(results)

    # Se prescrição vier vazia, tenta IA completa
    if not prescriptions.strip() and OPENAI_API_KEY:
        try:
            ai_dgn, ai_rx = ai_full_analysis(source, references_path)
            if ai_dgn: diagnosis += "\n\n" + ai_dgn
            if ai_rx: prescriptions = (prescriptions + "\n" + ai_rx).strip()
        except Exception as e:
            print(f"[AI full analysis fallback error] {e}")

    return diagnosis, prescriptions, name, gender, age, cpf, phone, doctor, birth_date

# ======================================================
# =============== WHATSAPP HELPERS =====================
# ======================================================

def _headers() -> dict:
    if not WHATSAPP_TOKEN:
        raise RuntimeError("WHATSAPP_TOKEN not configured")
    return {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}

def _endpoint() -> str:
    if not WHATSAPP_PHONE_NUMBER_ID:
        raise RuntimeError("WHATSAPP_PHONE_NUMBER_ID not configured")
    return f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/messages"

def _post_whatsapp(payload: dict) -> Optional[str]:
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

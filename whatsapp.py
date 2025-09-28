import os
import re
import json
import requests
from typing import Optional
from flask import current_app, url_for
from itsdangerous import URLSafeSerializer

# ------------------------------------------------------
# Configurações
# ------------------------------------------------------
WHATSAPP_API_URL = "https://graph.facebook.com/v18.0"
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")


# ------------------------------------------------------
# Internos
# ------------------------------------------------------
def _headers() -> dict:
    if not WHATSAPP_TOKEN:
        raise RuntimeError("WHATSAPP_TOKEN is not configured")
    return {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }


def _endpoint() -> str:
    if not WHATSAPP_PHONE_NUMBER_ID:
        raise RuntimeError("WHATSAPP_PHONE_NUMBER_ID is not configured")
    return f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/messages"


def _post_whatsapp(payload: dict) -> Optional[str]:
    """
    Envia payload para WhatsApp Cloud API.
    Retorna None em caso de sucesso ou string de erro em caso de falha.
    """
    print("[WA DEBUG] _post_whatsapp called")
    try:
        ep = _endpoint()
        print("[WA DEBUG] Endpoint:", ep)
        print("[WA DEBUG] Payload:", json.dumps(payload, ensure_ascii=False))
        resp = requests.post(ep, headers=_headers(), json=payload, timeout=30)
        print("[WA DEBUG] HTTP status:", resp.status_code)
        print("[WA DEBUG] Response body:", resp.text)

        if resp.status_code not in (200, 201):
            try:
                data = resp.json()
            except Exception:
                data = {"raw": resp.text}
            return f"WA API error {resp.status_code}: {data}"

        try:
            data = resp.json()
            wa_id = (data.get("contacts") or [{}])[0].get("wa_id")
            msg_id = (data.get("messages") or [{}])[0].get("id")
            if wa_id:
                print(f"[WA DEBUG] Contact mapping: input_to={payload.get('to')} -> wa_id={wa_id}")
            if msg_id:
                print(f"[WA DEBUG] Message accepted: id={msg_id}")
        except Exception as parse_err:
            print("[WA DEBUG] Could not parse JSON for wa_id/message_id:", parse_err)

        return None
    except Exception as e:
        print("[WA DEBUG] Exception in _post_whatsapp:", e)
        return f"WA request failed: {e}"


def normalize_phone(msisdn: str) -> str:
    """
    Normaliza número para o formato aceito pelo WhatsApp.
    """
    if not msisdn:
        return msisdn
    digits = re.sub(r"\D", "", msisdn)
    if digits.startswith("55") and len(digits) in (12, 13):
        return digits
    if len(digits) == 11 and not digits.startswith("55"):
        return f"55{digits}"
    return digits


# ------------------------------------------------------
# Cotações
# ------------------------------------------------------
def send_quote_whatsapp(
    supplier_name: str,
    quote_title: str,
    phone: str,
    quote_items: list[str],
    response_url: str,
) -> Optional[str]:
    if not phone:
        return "Nenhum telefone do fornecedor informado."
    items_text = "\n".join(f"- {it}" for it in quote_items) if quote_items else "-"
    payload = {
        "messaging_product": "whatsapp",
        "to": normalize_phone(phone),
        "type": "template",
        "template": {
            "name": "cotacao_rafahmed",
            "language": {"code": "pt_BR"},
            "components": [{
                "type": "body",
                "parameters": [
                    {"type": "text", "text": supplier_name or "-"},
                    {"type": "text", "text": quote_title or "-"},
                    {"type": "text", "text": items_text},
                    {"type": "text", "text": response_url or "-"},
                ],
            }],
        },
    }
    return _post_whatsapp(payload)


# ------------------------------------------------------
# Envio de PDFs
# ------------------------------------------------------
def send_pdf_whatsapp_template(
    template_name: str,
    display_name: str,
    patient_name: str,
    phone_number: str,
    patient_id: int,
) -> Optional[str]:
    if not phone_number:
        return "Nenhum telefone informado para envio."
    s = URLSafeSerializer(current_app.config["SECRET_KEY"])
    token = s.dumps(patient_id)
    analyzed_link = url_for("public_download", token=token, _external=True)
    payload = {
        "messaging_product": "whatsapp",
        "to": normalize_phone(phone_number),
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": "pt_BR"},
            "components": [{
                "type": "body",
                "parameters": [
                    {"type": "text", "text": display_name or "-"},
                    {"type": "text", "text": patient_name or "-"},
                    {"type": "text", "text": analyzed_link},
                ],
            }],
        },
    }
    return _post_whatsapp(payload)


def send_pdf_whatsapp_patient(
    patient_name: str,
    patient_phone: str,
    patient_id: int,
    clinic_phone: Optional[str] = None,
) -> Optional[str]:
    if not patient_phone:
        return "Nenhum telefone do paciente informado."
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
                    {"type": "text", "text": clinic_phone or "-"},
                ],
            }],
        },
    }
    return _post_whatsapp(payload)


# ------------------------------------------------------
# Lembretes de agenda (5 variáveis)
# ------------------------------------------------------
def send_reminder_doctor(
    clinic_phone: str,
    patient_name: str,
    clinic_name: str,
    date_str: str,
    time_start: str,
    time_end: str
) -> Optional[str]:
    """
    Lembrete para o médico (clínica) no dia da consulta.
    Usa template 'appointment_scheduling' com 5 variáveis.
    """
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


def send_reminder_patient(
    patient_phone: str,
    patient_name: str,
    clinic_name: str,
    date_str: str,
    time_start: str,
    time_end: str
) -> Optional[str]:
    """
    Lembrete para o paciente um dia antes da consulta.
    Usa template 'appointment_scheduling' com 5 variáveis.
    """
    if not patient_phone:
        return "Nenhum telefone do paciente informado."
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


# ------------------------------------------------------
# Texto livre (opcional)
# ------------------------------------------------------
def send_text(to_phone: str, text: str) -> Optional[str]:
    to = normalize_phone(to_phone)
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"preview_url": True, "body": text},
    }
    return _post_whatsapp(payload)

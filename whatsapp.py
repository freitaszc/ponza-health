import os
import re
import json
import requests
from typing import Optional, List
from difflib import get_close_matches

WHATSAPP_API_URL = "https://graph.facebook.com/v18.0"
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")

# If you want admin alerts on failures, set this in the environment
ADMIN_WHATSAPP = os.getenv("ADMIN_WHATSAPP", "").strip()


# ----------------------------
# Helpers
# ----------------------------
def _headers() -> dict:
    if not WHATSAPP_TOKEN:
        raise RuntimeError("WHATSAPP_TOKEN is not configured")
    return {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }


def _endpoint() -> str:
    if not WHATSAPP_PHONE_NUMBER_ID:
        raise RuntimeError("WHATSAPP_PHONE_NUMBER_ID is not configured")
    return f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/messages"


def _post_whatsapp(payload: dict) -> Optional[str]:
    """
    Sends payload to WhatsApp Cloud API.
    Returns None on success or the error string on failure.
    """
    try:
        resp = requests.post(_endpoint(), headers=_headers(), json=payload, timeout=30)
        # API returns 200 OK; some SDks treat 201 as success too, so accept both
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
    """
    Normalizes a phone number for WhatsApp Cloud API.
    - Strip non-digits
    - If BR mobile without DDI (11 digits), prefix 55
    - If starts with DDI already (e.g., 55...), keep it
    - Keep 12/13 digits for Brazil (with 9th digit)
    """
    if not msisdn:
        return msisdn
    digits = re.sub(r"\D", "", msisdn)

    # Already has DDI 55 and typical BR length
    if digits.startswith("55") and len(digits) in (12, 13):
        return digits

    # Local BR mobile without DDI (11 digits -> add 55)
    if len(digits) == 11 and not digits.startswith("55"):
        return f"55{digits}"

    # International already (e.g., 1..., 44..., 351..., etc.)
    return digits


def _template_payload(to: str, name: str, components: List[dict]) -> dict:
    """
    Produces a WhatsApp template payload.
    """
    return {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": name,
            "language": {"code": "pt_BR"},
            "components": components,
        },
    }


def _send_admin_alert(text: str) -> None:
    """
    Optional admin alert for debugging failures (if ADMIN_WHATSAPP set).
    """
    if not ADMIN_WHATSAPP:
        return
    payload = {
        "messaging_product": "whatsapp",
        "to": normalize_phone(ADMIN_WHATSAPP),
        "type": "text",
        "text": {"preview_url": False, "body": f"[PonzaHealth] {text}"},
    }
    _post_whatsapp(payload)


# ----------------------------
# Public senders
# ----------------------------
def send_pdf_whatsapp(
    doctor_name: str,
    patient_name: str,
    analyzed_pdf_link: str,
    original_pdf_link: str,
    phone_number: str
) -> Optional[str]:
    """
    Envia mensagem via template com os links do PDF analisado e original
    diretamente para o telefone fornecido no formulário de upload.
    NÃO usa json/doctors.json nem consulta tabela Doctor.
    """
    if not phone_number:
        return "Nenhum telefone informado para envio."

    to = normalize_phone(phone_number)
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": "relatorio_ponzahealth",
            "language": {"code": "pt_BR"},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": doctor_name or "-"},
                        {"type": "text", "text": patient_name or "-"},
                        {"type": "text", "text": analyzed_pdf_link or "-"},
                        {"type": "text", "text": original_pdf_link or "-"},
                    ],
                }
            ],
        },
    }
    return _post_whatsapp(payload)

def send_quote_whatsapp(
    supplier_name: str,
    phone: str,
    quote_title: str,
    quote_items: List[str],
    response_url: str,
) -> Optional[str]:
    """
    Sends a template message to a SUPPLIER with the quote details + response link.
    Returns None on success or an error string on failure.
    """
    if not phone:
        return f"Supplier '{supplier_name}' missing phone."
    to = normalize_phone(phone)
    if not to:
        return f"Supplier '{supplier_name}' invalid phone."

    # Collapse items into a short bullet list; WhatsApp template bodies have size limits
    items_text = "\n".join(f"• {it}" for it in (quote_items or [])[:10]).strip() or "-"

    # Template assumed: ponzahealth_cotacao
    # BODY params (example): 1) SupplierName  2) QuoteTitle  3) Items  4) ResponseURL
    body_params = [
        {"type": "text", "text": supplier_name or "-"},
        {"type": "text", "text": quote_title or "-"},
        {"type": "text", "text": items_text},
        {"type": "text", "text": response_url or "-"},
    ]
    payload = _template_payload(
        to=to,
        name="ponzahealth_cotacao",
        components=[{"type": "body", "parameters": body_params}],
    )

    err = _post_whatsapp(payload)
    if err:
        _send_admin_alert(f"send_quote_whatsapp error for {supplier_name}: {err}")
    return err


# ----------------------------
# Optional: media/document path (use only when 24h window is open)
# ----------------------------
def send_text(to_phone: str, text: str) -> Optional[str]:
    """
    Raw text helper (only succeeds if a conversation window is already open).
    """
    to = normalize_phone(to_phone)
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"preview_url": True, "body": text},
    }
    return _post_whatsapp(payload)

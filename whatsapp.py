import os
import re
import json
import requests
from difflib import get_close_matches

WHATSAPP_API_URL = "https://graph.facebook.com/v18.0"
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")


def normalize_phone(phone: str) -> str:
    """
    Normaliza número para o formato internacional esperado pelo WhatsApp Cloud API.
    - Remove caracteres não numéricos.
    - Se for um celular do Brasil sem DDI (11 dígitos), prefixa 55.
    - Se já começa com DDI (ex.: 55...), mantém.
    """
    if not phone:
        return phone
    digits = re.sub(r"\D", "", phone)

    if digits.startswith("55") and len(digits) in (12, 13):  # 12/13 because of the 9th digit added in Brazil
        return digits

    # if it doesnt have DDI
    if len(digits) == 11 and not digits.startswith("55"):
        return f"55{digits}"

    # if it already has + it corrects it
    if phone.startswith("+"):
        return digits

    return digits


def send_pdf_whatsapp(doctor_name: str, patient_name: str,
                      analyzed_pdf_link: str, original_pdf_link: str) -> str | None:
    """
    Envia mensagem WhatsApp para o médico com os links do PDF analisado e original.
    Retorna None se sucesso ou uma mensagem de erro.
    """
    # Carregar médicos
    with open("json/doctors.json", "r", encoding="utf-8") as file:
        doctors = json.load(file)

    doctor_names = [d["name"] for d in doctors]
    matches = get_close_matches(doctor_name, doctor_names, n=1, cutoff=0.6)

    if not matches:
        return f"Doctor '{doctor_name}' not found in the system."

    doctor = next((d for d in doctors if d["name"] == matches[0]), None)

    if not doctor or not doctor.get("phone"):
        return f"Doctor '{matches[0]}' not found or phone not registered."

    # ✅ Normaliza número para E.164
    phone_number = normalize_phone(doctor["phone"])

    if not phone_number:
        return f"Invalid phone format for doctor '{matches[0]}'."

    # Envio WhatsApp
    try:
        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }

        payload = {
            "messaging_product": "whatsapp",
            "to": phone_number,
            "type": "template",
            "template": {
                "name": "relatorio_ponzahealth",
                "language": {"code": "pt_BR"},
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": doctor_name},
                            {"type": "text", "text": patient_name},
                            {"type": "text", "text": analyzed_pdf_link},
                            {"type": "text", "text": original_pdf_link}
                        ]
                    }
                ]
            }
        }

        response = requests.post(
            f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/messages",
            headers=headers,
            json=payload
        )

        if response.status_code != 200:
            return f"Error sending message: {response.text}"

        return None  # sucesso

    except Exception as e:
        return f"Unexpected error: {e}"


def send_quote_whatsapp(supplier_name: str, phone: str,
                        quote_title: str, quote_items: list[str],
                        response_url: str) -> None:
    """
    Envia mensagem WhatsApp para o fornecedor com os detalhes da cotação.
    """
    if not phone or not WHATSAPP_PHONE_NUMBER_ID or not WHATSAPP_TOKEN:
        print("[ERRO] Informações de envio WhatsApp ausentes.")
        return

    # ✅ Normaliza número do fornecedor
    phone = normalize_phone(phone)

    if not phone:
        print(f"[ERRO] Telefone inválido para fornecedor {supplier_name}")
        return

    # Formatar itens
    items_text = " | ".join([
        item.strip().replace("\n", " ").replace("\t", " ")
        for item in quote_items
    ])

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {
            "name": "ponzahealth_cotacao",
            "language": {"code": "pt_BR"},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": supplier_name},
                        {"type": "text", "text": quote_title},
                        {"type": "text", "text": items_text},
                        {"type": "text", "text": response_url}
                    ]
                }
            ]
        }
    }

    try:
        response = requests.post(
            f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/messages",
            headers=headers,
            json=payload
        )

        if response.status_code != 200:
            print(f"[Erro WhatsApp - {supplier_name}] {response.text}")
        else:
            print(f"[WhatsApp enviado] para {supplier_name} ({phone})")

    except Exception as e:
        print(f"[Erro inesperado ao enviar WhatsApp para {supplier_name}] {e}")

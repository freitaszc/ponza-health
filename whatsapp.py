import os
import json
import requests
from difflib import get_close_matches

WHATSAPP_API_URL = "https://graph.facebook.com/v18.0"
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")


def enviar_pdf_whatsapp(medico_nome: str, paciente_nome: str, pdf_link_analisado: str, pdf_link_original: str):
    """
    Envia a mensagem WhatsApp com os dois links dos PDFs já gerados.
    """
    # 1. Busca o telefone do médico
    with open("json/doctors.json", "r", encoding="utf-8") as f:
        doctors = json.load(f)

    nomes_dos_medicos = [d["name"] for d in doctors]
    matches = get_close_matches(medico_nome, nomes_dos_medicos, n=1, cutoff=0.6)

    if not matches:
        return f"Médico '{medico_nome}' não encontrado no sistema."

    medico = next((d for d in doctors if d["name"] == matches[0]), None)

    if not medico or not medico.get("phone"):
        return f"Médico '{matches[0]}' não encontrado ou sem telefone cadastrado."

    telefone_destino = medico["phone"]

    # 2. Envia a mensagem WhatsApp
    try:
        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }

        payload = {
            "messaging_product": "whatsapp",
            "to": telefone_destino,
            "type": "template",
            "template": {
                "name": "relatorio_bioo3",
                "language": { "code": "pt_BR" },
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": medico_nome},
                            {"type": "text", "text": paciente_nome},
                            {"type": "text", "text": pdf_link_analisado},
                            {"type": "text", "text": pdf_link_original}
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
            return f"Erro ao enviar mensagem: {response.text}"

        return None  # sucesso

    except Exception as e:
        return f"Erro inesperado: {e}"

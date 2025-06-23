import requests
import json
import os
from typing import Optional

WHATSAPP_API_URL = "https://graph.facebook.com/v18.0"
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")

def enviar_pdf_whatsapp(medico_nome: str, caminho_pdf_resultado: str, caminho_pdf_original: str) -> Optional[str]:
    with open("json/doctors.json", "r", encoding="utf-8") as f:
        doctors = json.load(f)

    medico = next((d for d in doctors if d["name"].lower() == medico_nome.lower()), None)
    if not medico or not medico.get("phone"):
        return f"Médico '{medico_nome}' não encontrado ou sem telefone cadastrado."

    telefone_destino = medico["phone"]

    try:
        headers_upload = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}"
        }

        # Envia resultado da BioO3
        with open(caminho_pdf_resultado, "rb") as f1:
            resp1 = requests.post(
                f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                headers=headers_upload,
                files={"file": (os.path.basename(caminho_pdf_resultado), f1, "application/pdf")},
                data={"messaging_product": "whatsapp"}
            )
            resp1.raise_for_status()
            media_id_resultado = resp1.json()["id"]

        # Envia PDF original
        with open(caminho_pdf_original, "rb") as f2:
            resp2 = requests.post(
                f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/media",
                headers=headers_upload,
                files={"file": (os.path.basename(caminho_pdf_original), f2, "application/pdf")},
                data={"messaging_product": "whatsapp"}
            )
            resp2.raise_for_status()
            media_id_original = resp2.json()["id"]

        headers_msg = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }

        payload1 = {
            "messaging_product": "whatsapp",
            "to": telefone_destino,
            "type": "document",
            "document": {
                "id": media_id_resultado,
                "filename": os.path.basename(caminho_pdf_resultado)
            }
        }
        payload2 = {
            "messaging_product": "whatsapp",
            "to": telefone_destino,
            "type": "document",
            "document": {
                "id": media_id_original,
                "filename": os.path.basename(caminho_pdf_original)
            }
        }

        requests.post(f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/messages", headers=headers_msg, json=payload1).raise_for_status()
        requests.post(f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/messages", headers=headers_msg, json=payload2).raise_for_status()

        return "PDFs enviados com sucesso."
    except requests.exceptions.RequestException as e:
        return f"Erro ao enviar: {e}"

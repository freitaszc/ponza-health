import os
import json
import requests

WHATSAPP_API_URL = "https://graph.facebook.com/v18.0"
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")

def enviar_pdf_whatsapp(medico_nome: str, paciente_nome: str, pdf_link_analisado: str, pdf_link_original: str, template_name: str = "relatorio_bioo3"):
    with open("json/doctors.json", "r", encoding="utf-8") as f:
        doctors = json.load(f)

    medico = next((d for d in doctors if d["name"].lower() == medico_nome.lower()), None)
    if not medico or not medico.get("phone"):
        return f"Médico '{medico_nome}' não encontrado ou sem telefone cadastrado."

    telefone_destino = medico["phone"]

    try:
        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }

        # Ajustar o idioma dependendo do template
        language_code = "pt_BR" if template_name != "hello_world" else "en_US"

        # Montar o payload
        payload = {
            "messaging_product": "whatsapp",
            "to": telefone_destino,
            "type": "template",
            "template": {
                "name": template_name,
                "language": { "code": language_code }
            }
        }

        # Adicionar parâmetros se o template não for o hello_world
        if template_name != "hello_world":
            payload["template"]["components"] = [
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

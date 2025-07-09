import os
import json
import requests
from difflib import get_close_matches

WHATSAPP_API_URL = "https://graph.facebook.com/v18.0"
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")


def send_pdf_whatsapp(doctor_name, patient_name, analyzed_pdf_link, original_pdf_link):
    """
    Sends a WhatsApp message with the links to the analyzed and original PDFs.
    """
    # Load doctors data
    with open("json/doctors.json", "r", encoding="utf-8") as file:
        doctors = json.load(file)

    doctor_names = [d["name"] for d in doctors]
    matches = get_close_matches(doctor_name, doctor_names, n=1, cutoff=0.6)

    if not matches:
        return f"Doctor '{doctor_name}' not found in the system."

    doctor = next((d for d in doctors if d["name"] == matches[0]), None)

    if not doctor or not doctor.get("phone"):
        return f"Doctor '{matches[0]}' not found or phone not registered."

    phone_number = doctor["phone"]

    # Send WhatsApp message
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
                "name": "relatorio_bioo3",
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

        return None  # success

    except Exception as e:
        return f"Unexpected error: {e}"

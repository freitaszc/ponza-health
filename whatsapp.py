import os
import json
import requests
from difflib import get_close_matches
from flask import render_template, url_for
import weasyprint

WHATSAPP_API_URL = "https://graph.facebook.com/v18.0"
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")


def gerar_pdf_formatado(patient_info, result_text, paciente_nome):
    """
    Gera um PDF formatado com o template 'result.html' e CSS 'pdf.css',
    salvando o PDF em 'static/output/'.
    """
    caminho_pdf = os.path.join("static", "output", f"Relatorio_{paciente_nome}.pdf")
    html = render_template("result.html", patient_info=patient_info, result_text=result_text)
    css = weasyprint.CSS("static/css/pdf.css")
    pdf = weasyprint.HTML(string=html).write_pdf(stylesheets=[css])

    if pdf is None:
        raise ValueError("Falha ao gerar o PDF com WeasyPrint.")

    with open(caminho_pdf, "wb") as f:
        f.write(pdf)

    return caminho_pdf  # Caminho local do PDF gerado


def gerar_link_pdf(paciente_nome):
    """
    Gera o link absoluto para acessar o PDF salvo.
    """
    return url_for('static', filename=f"output/Relatorio_{paciente_nome}.pdf", _external=True)


def gerar_link_pdf_original(nome_arquivo):
    """
    Gera o link absoluto para o PDF original (enviado no upload).
    """
    return url_for('static', filename=f"uploads/{nome_arquivo}", _external=True)


def enviar_pdf_whatsapp(medico_nome: str, paciente_nome: str, patient_info, result_text, nome_pdf_original):
    """
    Gera o PDF formatado, cria os links e envia a mensagem WhatsApp com os dois links.
    """
    # 1. Gera o PDF formatado e salva
    gerar_pdf_formatado(patient_info, result_text, paciente_nome)
    
    # 2. Gera os links do PDF analisado e do PDF original
    pdf_link = gerar_link_pdf(paciente_nome)
    pdf_link_original = gerar_link_pdf_original(nome_pdf_original)

    # 3. Busca o telefone do médico
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

    # 4. Envia a mensagem WhatsApp
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
                            {"type": "text", "text": pdf_link},
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

        return None  #sucess

    except Exception as e:
        return f"Erro inesperado: {e}"

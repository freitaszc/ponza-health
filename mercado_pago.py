import mercadopago
import os
from dotenv import load_dotenv

load_dotenv()

access_token = os.getenv("MERCADO_PAGO_ACCESS_TOKEN")
sdk = mercadopago.SDK(access_token)

def gerar_link_pagamento(pacote, valor):
    preference_data = {
        "items": [
            {
                "title": f"Pacote {pacote} análises",
                "quantity": 1,
                "currency_id": "BRL",
                "unit_price": float(valor)
            }
        ],
        "back_urls": {
            "success": "https:bioo3.com/pagamento-sucesso",
            "failure": "https:bioo3.com/pagamento-falha",
            "pending": "https:bioo3.com/pagamento-pendente"
        },
        "auto_return": "approved"
    }

    preference_response = sdk.preference().create(preference_data)
    print("=== RESPOSTA DO MERCADO PAGO ===")
    print(preference_response)
    print("================================")

    if preference_response['status'] == 201:
        return preference_response['response'].get('init_point', '')
    else:
        return '' 

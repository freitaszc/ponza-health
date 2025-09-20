import os
import mercadopago
from dotenv import load_dotenv
from datetime import datetime, timedelta

# Carrega variáveis de ambiente
load_dotenv()

access_token = os.getenv("MERCADO_PAGO_ACCESS_TOKEN")
sdk = mercadopago.SDK(access_token)


def generate_payment_link(package, amount):
    """
    Gera link de pagamento Mercado Pago para compra de pacotes de análises.
    """
    preference_data = {
        "items": [
            {
                "title": f"Pacote de {package} análises - Ponza Lab",
                "quantity": 1,
                "currency_id": "BRL",
                "unit_price": float(amount)
            }
        ],
        "back_urls": {
            "success": "https://PonzaHealth.com/payments/success",
            "failure": "https://PonzaHealth.com/payments/failure",
            "pending": "https://PonzaHealth.com/payments/pending"
        },
        "auto_return": "approved"
    }

    preference_response = sdk.preference().create(preference_data)
    print("=== MERCADO PAGO RESPONSE (Pacote) ===")
    print(preference_response)
    print("=======================================")

    if preference_response['status'] == 201:
        return preference_response['response'].get('init_point', '')
    else:
        return ''


def generate_subscription_link(user_id):
    """
    Gera link de pagamento Mercado Pago para a assinatura mensal de R$ 79,90.
    Quando o pagamento é aprovado, o webhook / rota de callback deverá
    atualizar o usuário no banco de dados:
       user.plan_status = 'paid'
       user.plan_expires_at = datetime.utcnow() + timedelta(days=30)
    """
    preference_data = {
        "items": [
            {
                "title": "Assinatura mensal Ponza Health",
                "description": "Plano mensal com acesso por 30 dias",
                "quantity": 1,
                "currency_id": "BRL",
                "unit_price": 79.90
            }
        ],
        "back_urls": {
            "success": "https://PonzaHealth.com/subscription/success",
            "failure": "https://PonzaHealth.com/subscription/failure",
            "pending": "https://PonzaHealth.com/subscription/pending"
        },
        "auto_return": "approved",
        # Envia id do usuário para identificar no webhook
        "metadata": {
            "user_id": str(user_id),
            "type": "subscription"
        }
    }

    preference_response = sdk.preference().create(preference_data)
    print("=== MERCADO PAGO RESPONSE (Assinatura) ===")
    print(preference_response)
    print("===========================================")

    if preference_response['status'] == 201:
        return preference_response['response'].get('init_point', '')
    else:
        return ''

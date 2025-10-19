import os
import stripe
from dotenv import load_dotenv

load_dotenv()

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
BASE_URL = os.getenv("APP_BASE_URL", "https://ponzahealth.com.br")

# -------------------------------------------------------------------
# ASSINATURAS (Mensal e Anual)
# -------------------------------------------------------------------

def generate_subscription_link(user_id, plan="monthly"):
    """Cria um link de checkout Stripe para o plano mensal ou anual (usando os price_id reais)."""
    try:
        if plan == "yearly":
            price_id = os.getenv("STRIPE_PRICE_YEARLY")  # ex: price_1Q6JhTA2fghij789101kl
            plan_name = "Assinatura anual Ponza Health"
        else:
            price_id = os.getenv("STRIPE_PRICE_MONTHLY")  # ex: price_1Q6JgHA2abcde123456xyz
            plan_name = "Assinatura mensal Ponza Health"

        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="subscription",
            line_items=[{
                "price": price_id,
                "quantity": 1,
            }],
            metadata={"user_id": str(user_id), "plan": plan},
            success_url=f"{BASE_URL}/subscription/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{BASE_URL}/subscription/cancel",
        )

        print(f"[Stripe] ✅ Created subscription link for {plan_name} (user_id={user_id})")
        return session.url

    except Exception as e:
        print(f"[Stripe] ❌ Error creating subscription ({plan}):", e)
        return ""


# -------------------------------------------------------------------
# PACOTES DE ANÁLISES (50, 150, 500)
# -------------------------------------------------------------------

def generate_package_link(package):
    """Cria link de pagamento único para pacotes de 50, 150 ou 500 análises."""
    try:
        # Mapeia os pacotes aos seus price_ids criados no Stripe
        price_ids = {
            50: os.getenv("STRIPE_PRICE_PACKAGE_50"),
            150: os.getenv("STRIPE_PRICE_PACKAGE_150"),
            500: os.getenv("STRIPE_PRICE_PACKAGE_500"),
        }

        price_id = price_ids.get(package)
        if not price_id:
            raise ValueError(f"Nenhum price_id configurado para o pacote {package}")

        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="payment",
            line_items=[{
                "price": price_id,
                "quantity": 1,
            }],
            success_url=f"{BASE_URL}/payments/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{BASE_URL}/payments/cancel",
        )

        print(f"[Stripe] ✅ Created payment link for {package} analyses package")
        return session.url

    except Exception as e:
        print("[Stripe] ❌ Error creating package link:", e)
        return ""

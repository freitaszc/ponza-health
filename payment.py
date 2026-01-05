import os
import stripe
from dotenv import load_dotenv

load_dotenv()

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
BASE_URL = os.getenv("APP_BASE_URL", "https://ponzahealth.com.br")
PACKAGE_PRICE_CENTS = {
    50: 12000,
    150: 30000,
    500: 80000,
}

# -------------------------------------------------------------------
# ASSINATURAS (Mensal e Anual)
# -------------------------------------------------------------------

def generate_subscription_link(user_id, plan="monthly"):
    """Cria um link de checkout Stripe para o plano mensal ou anual (usando os price_id reais)."""
    try:
        if plan == "yearly":
            price_id = os.getenv("STRIPE_PRICE_YEARLY")
            plan_name = "Assinatura anual Ponza Health"
        else:
            price_id = os.getenv("STRIPE_PRICE_MONTHLY")  
            plan_name = "Assinatura mensal Ponza Health"

        payment_methods = ["card", "boleto"]

        def _create_checkout(methods):
            return stripe.checkout.Session.create(
                payment_method_types=methods,
                mode="subscription",
                line_items=[{
                    "price": price_id,
                    "quantity": 1,
                }],
                metadata={"user_id": str(user_id), "plan": plan},
                success_url=f"{BASE_URL}/subscription/success?session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{BASE_URL}/subscription/cancel",
            )

        try:
            session = _create_checkout(payment_methods)
        except stripe.error.InvalidRequestError as exc:  # type: ignore[attr-defined]
            param = (getattr(exc, "param", "") or "").lower()
            message = str(exc).lower()
            if "payment_method_types" in param or "payment_method_types" in message or "boleto" in message:
                print("[Stripe] Boleto indisponivel para assinatura. Usando cartao.", exc)
                session = _create_checkout(["card"])
            else:
                raise

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

        if package not in price_ids:
            raise ValueError(f"Pacote invalido: {package}")
        price_id = price_ids.get(package) or ""

        def _create(line_items):
            return stripe.checkout.Session.create(
                payment_method_types=["card", "boleto"],
                mode="payment",
                line_items=line_items,
                success_url=f"{BASE_URL}/payments/success?session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{BASE_URL}/payments/cancel",
            )

        try:
            session = _create([{
                "price": price_id,
                "quantity": 1,
            }])
        except stripe.error.InvalidRequestError as exc:  # type: ignore[attr-defined]
            param = (getattr(exc, "param", "") or "").lower()
            message = str(exc).lower()
            if "price" not in param and "price" not in message:
                raise
            amount_cents = PACKAGE_PRICE_CENTS.get(package)
            if not amount_cents:
                raise
            session = _create([{
                "price_data": {
                    "currency": "brl",
                    "unit_amount": int(amount_cents),
                    "product_data": {"name": f"Pacote {package} analises"},
                },
                "quantity": 1,
            }])

        print(f"[Stripe] ✅ Created payment link for {package} analyses package")
        return session.url

    except Exception as e:
        print("[Stripe] ❌ Error creating package link:", e)
        return ""

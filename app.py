import os
import io
import re
import secrets
import stripe
from flask_migrate import Migrate
from io import BytesIO
from functools import wraps
from typing import Any, Optional, Callable, cast
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone, date
from zoneinfo import ZoneInfo
from uuid import uuid4
import json
import tempfile
import requests
from itsdangerous import URLSafeTimedSerializer, URLSafeSerializer, BadSignature, SignatureExpired
from flask_mail import Mail, Message
from prescription import (
    analyze_pdf,
    send_pdf_whatsapp_template,
    send_pdf_whatsapp_patient,
    send_reminder_doctor,
    send_reminder_patient,
    send_quote_whatsapp,
)

from dotenv import load_dotenv
from flask import (
    Flask, Blueprint, render_template, request, redirect, url_for,
    session, flash, jsonify, abort, send_file, g, current_app, send_file, abort
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import select, func, or_
from werkzeug.middleware.proxy_fix import ProxyFix
from apscheduler.schedulers.background import BackgroundScheduler #type:ignore
from jinja2 import TemplateNotFound

from models import (
    db, User, Patient, Doctor, Consult, PackageUsage,
    Supplier, Product, AgendaEvent, Quote,
    SecureFile, PdfFile, WaitlistItem, ScheduledEmail,
    StockMovement,
)

# ------------------------------------------------------------------------------
# Inicialização / Config
# ------------------------------------------------------------------------------
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))
app = Flask(__name__)

if os.getenv("RENDER"):
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)  # type: ignore

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), 'instance'))
os.makedirs(BASE_DIR, exist_ok=True)
STATIC_DIR = os.path.join(app.root_path, 'static')
os.makedirs(STATIC_DIR, exist_ok=True)
UPLOAD_FOLDER = os.path.join(STATIC_DIR, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_hex(32)
app.config['SECRET_KEY'] = SECRET_KEY

# Uploads
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}
DEFAULT_USER_IMAGE = "images/user-icon.png"
DEFAULT_PATIENT_IMAGE = "images/admin_profile.png"

app.config["PUBLIC_BASE_URL"] = (
    os.getenv("PUBLIC_BASE_URL")
    or os.getenv("APP_BASE_URL")
    or os.getenv("PUBLIC_APP_URL")
)

# Email
app.config.update(
    MAIL_SERVER=os.getenv("SMTP_SERVER", "smtp.gmail.com"),
    MAIL_PORT=int(os.getenv("SMTP_PORT", 587)),
    MAIL_USE_TLS=(os.getenv("MAIL_USE_TLS", "true").strip().lower() == "true"),
    MAIL_USERNAME=os.getenv("SMTP_USERNAME"),
    MAIL_PASSWORD=os.getenv("SMTP_PASSWORD"),
    MAIL_DEFAULT_SENDER=(
        "Ponza Health",
        os.getenv("EMAIL_FROM") or os.getenv("SMTP_USERNAME")
    ),
)

mail = Mail(app)

def send_email(subject, recipients, html=None, body=None, sender=None, reply_to=None, inline_images=None):
    """
    Envia e-mail com suporte a imagens inline via CID.
    inline_images deve ser uma lista de dicts: [{"filename": "logo.png", "path": "static/images/7.png", "cid": "logo"}]
    """
    msg = Message(
        subject=subject,
        recipients=recipients,
        sender=sender or app.config["MAIL_DEFAULT_SENDER"],
        reply_to=reply_to
    )
    if html:
        msg.html = html
    if body:
        msg.body = body

    # 🔑 Adiciona imagens inline (se houver)
    if inline_images:
        for img in inline_images:
            with app.open_resource(img["path"]) as fp:
                msg.attach(
                    img["filename"],      # nome do arquivo
                    "image/png",          # tipo MIME (ajuste se usar .jpg)
                    fp.read(),
                    "inline",
                    headers={"Content-ID": f"<{img['cid']}>"}
                )

    mail.send(msg)

def allowed_file(filename: str) -> bool:
    return bool(filename) and '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# Configurações de e-mail (SMTP)
app.config.update(
    MAIL_SERVER=os.getenv("SMTP_SERVER", "smtp.gmail.com"),
    MAIL_PORT=int(os.getenv("SMTP_PORT", 587)),
    MAIL_USE_TLS=(os.getenv("MAIL_USE_TLS", "true").strip().lower() == "true"),
    MAIL_USERNAME=os.getenv("SMTP_USERNAME"),
    MAIL_PASSWORD=os.getenv("SMTP_PASSWORD"),
    MAIL_DEFAULT_SENDER=os.getenv("EMAIL_FROM")  # deve ser igual a SMTP_USERNAME
)
mail = Mail(app)

# Serializer para tokens
ts = URLSafeTimedSerializer(app.config['SECRET_KEY'])

# ------------------------------------------------------------------------------
# Database (Supabase PostgreSQL)
# ------------------------------------------------------------------------------

def normalize_db_url(url: str) -> str:
    """Normaliza a URL do banco, garantindo compatibilidade com SQLAlchemy e SSL."""
    if not url:
        return url
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://") and "+psycopg2" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    if "sslmode=" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


# Lê a URL do Supabase do .env
SUPABASE_DATABASE_URL = os.getenv("SUPABASE_DATABASE_URL")

if SUPABASE_DATABASE_URL:
    DATABASE_URL = normalize_db_url(SUPABASE_DATABASE_URL)
else:
    # Fallback local para testes
    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), 'instance'))
    os.makedirs(BASE_DIR, exist_ok=True)
    db_path = os.path.join(BASE_DIR, 'web.db')
    DATABASE_URL = f"sqlite:///{db_path}"

# Configura o SQLAlchemy para conectar ao Supabase
app.config.update(
    SQLALCHEMY_DATABASE_URI=DATABASE_URL,
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SQLALCHEMY_ENGINE_OPTIONS={
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "pool_size": int(os.getenv("DB_POOL_SIZE", "5")),
        "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "5")),
    },
)

db.init_app(app)
migrate = Migrate(app, db)

# ------------------------------------------------------------------------------
# Conexão e verificação
# ------------------------------------------------------------------------------
with app.app_context():
    try:
        from sqlalchemy import inspect
        insp = inspect(db.engine)
        print("[DB] ✅ Conectado ao Supabase PostgreSQL com sucesso!")
        print(f"[DB] Tabelas detectadas: {insp.get_table_names()}")
    except Exception as e:
        print("[DB] ❌ Erro ao conectar ao Supabase:", e)

# ------------------------------------------------------------------------------
# Migração mínima (não necessária, pois o Supabase já tem as tabelas)
# ------------------------------------------------------------------------------
def apply_minimal_migrations():
    """Desativada — o Supabase já possui todas as tabelas e colunas criadas."""
    pass

# ------------------------------------------------------------------------------
# Funções auxiliares de armazenamento de PDFs
# ------------------------------------------------------------------------------
def _save_pdf_bytes_to_db(*, user_id: int, patient_id: Optional[int], consult_id: Optional[int],
                          original_name: str, data: bytes, kind: str) -> int:
    """
    Guarda o PDF em SecureFile (blob) + PdfFile (metadados/vínculo) e retorna o id do PdfFile.
    """
    unique_name = f"{secure_filename(os.path.splitext(original_name)[0])}_{int(datetime.utcnow().timestamp())}.pdf"
    sf = SecureFile(
        user_id=user_id,
        kind=kind,
        filename=unique_name,
        mime_type="application/pdf",
        size_bytes=len(data),
        data=data,
    )
    db.session.add(sf)
    db.session.flush()  # precisa do sf.id

    pf = PdfFile(
        filename=unique_name,
        original_name=original_name,
        size_bytes=len(data),
        secure_file_id=sf.id,
        patient_id=patient_id,
        consult_id=consult_id,
    )
    db.session.add(pf)
    db.session.commit()
    return pf.id


def _serve_pdf_from_db(pdf_file_id: int, *, download_name: Optional[str] = None):
    """
    Envia um PDF armazenado no banco (verifica o owner antes).
    """
    u = current_user()
    pf = PdfFile.query.get_or_404(pdf_file_id)
    sf = pf.secure_file
    if not sf or (sf.user_id is not None and sf.user_id != u.id):
        abort(403)

    bio = BytesIO(sf.data)
    bio.seek(0)

    return send_file(
        bio,
        as_attachment=bool(download_name),
        download_name=download_name or pf.original_name or pf.filename,
        mimetype=sf.mime_type or "application/pdf",
    )

# ----------------------------------------–-------------------------------------
# Admin
# ------------------------------------------------------------------------------
@app.route("/admin/users", methods=["GET", "POST"])
def admin_users():
    u = get_logged_user()
    if not u or (u.username or "").lower() != "admin":
        abort(403)

    all_users = User.query.order_by(User.created_at.desc()).all()
    # Convert current time to date for comparisons in the template
    now = datetime.utcnow().date()
    return render_template("admin_users.html", users=all_users, now=now)


@app.route("/admin/users/delete/<int:user_id>", methods=["POST"])
def delete_user(user_id):
    u = get_logged_user()
    if not u or (u.username or "").lower() != "admin":
        abort(403)

    target = User.query.get_or_404(user_id)
    if (target.username or "").lower() == "admin":
        flash("Conta admin não pode ser excluída.", "error")
    else:
        db.session.delete(target)
        db.session.commit()
        flash("Usuário excluído com sucesso.", "success")
    return redirect(url_for("admin_users"))

@app.route("/admin/users/extend", methods=["POST"])
def admin_extend_subscription():
    u = get_logged_user()
    if not u or (u.username or "").lower() != "admin":
        abort(403)

    user_id = request.form.get("user_id", type=int)
    months: int = request.form.get("months", type=int) or 0
    if months <= 0:
        flash("Selecione um número válido de meses.", "warning")
        return redirect(url_for("admin_users"))

    target = User.query.get_or_404(user_id)
    if (target.username or "").lower() == "admin":
        flash("A conta admin não pode ser alterada.", "warning")
        return redirect(url_for("admin_users"))

    now = datetime.utcnow()

    # ✅ Ensure plan_expiration is datetime (not str)
    plan_exp = target.plan_expiration
    if isinstance(plan_exp, str):
        try:
            plan_exp = datetime.fromisoformat(plan_exp)
        except Exception:
            plan_exp = None

    # ✅ Choose base date for extension
    base_date = plan_exp if plan_exp and plan_exp > now else now

    target.plan_status = "paid"
    target.plan_expiration = base_date + timedelta(days=30 * months)

    db.session.commit()

    flash(f"Assinatura de {target.username} estendida por {months} mês(es).", "success")
    return redirect(url_for("admin_users"))


# ------------------------------------------------------------------------------
# Esqueci a senha
# ------------------------------------------------------------------------------
def _get_serializer():
    # SECRET_KEY precisa estar configurada no app (ou no .env e lida acima).
    return URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="pw-reset")

def generate_reset_token(email: str) -> str:
    return _get_serializer().dumps(email)

def verify_reset_token(token: str, max_age_seconds: int = 3600*24) -> str | None:
    # max_age_seconds = 24 horas
    try:
        return _get_serializer().loads(token, max_age=max_age_seconds)
    except SignatureExpired:
        return None
    except BadSignature:
        return None

@app.route("/forgot_password", methods=["GET", "POST"])
def pw_forgot():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        user = User.query.filter(func.lower(User.email) == email).first()

        if user:
            app.logger.info(f"Reset de senha solicitado para {email}")
            token = generate_reset_token(email)
            reset_link = url_for("pw_reset", token=token, _external=True)

            html = f"""
                <p>Olá!</p>
                <p>Recebemos uma solicitação para redefinir sua senha.</p>
                <p>Clique no link abaixo para continuar (válido por 24h):</p>
                <p><a href="{reset_link}">{reset_link}</a></p>
                <p>Se você não solicitou, ignore este e-mail.</p>
                <hr>
                <p>Ponza Health</p>
            """
            try:
                send_email(
                    subject="Redefinição de senha — Ponza Health",
                    recipients=[email],
                    html=html,
                )
            except Exception as e:
                app.logger.exception("Erro ao enviar e-mail de reset")

        flash("Se este e-mail existir, enviaremos um link de recuperação.", "info")
        return redirect(url_for("pw_forgot"))

    return render_template("pw_forgot.html")

# ------------------------------------------------------------------------------
# Reset de senha
# ------------------------------------------------------------------------------
@app.route("/reset_password/<token>", methods=["GET", "POST"])
def pw_reset(token):
    email = verify_reset_token(token)
    if not email:
        flash("Link inválido ou expirado. Solicite novamente.", "warning")
        return redirect(url_for("pw_forgot"))

    if request.method == "POST":
        new_password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""
        if len(new_password) < 8:
            flash("A senha deve ter pelo menos 8 caracteres.", "danger")
            return redirect(url_for("pw_reset", token=token))
        if new_password != confirm:
            flash("As senhas não coincidem.", "danger")
            return redirect(url_for("pw_reset", token=token))

        user = User.query.filter_by(email=email).first()
        if not user:
            flash("Usuário não encontrado.", "danger")
            return redirect(url_for("pw_forgot"))

        user.password_hash = generate_password_hash(new_password)
        db.session.commit()

        # E-mail opcional de confirmação
        try:
            send_email(
                subject="Sua senha foi alterada — Ponza Health",
                recipients=[email],
                html="""
                    <p>Olá!</p>
                    <p>A sua senha foi alterada com sucesso.</p>
                    <p>Se não foi você, entre em contato imediatamente.</p>
                    <hr>
                    <p>Ponza Health</p>
                """,
            )
        except Exception:
            app.logger.exception("Erro ao enviar e-mail de confirmação de troca de senha")

        flash("Senha alterada com sucesso. Faça login.", "success")
        return redirect(url_for("login"))

    # GET
    return render_template("reset_password.html", token=token)

# ------------------------------------------------------------------------------
# Helpers / Auth
# ------------------------------------------------------------------------------
@app.template_filter("brt")
def brt(dt):
    """Converte datetime/date/str para horário de Brasília."""
    if not dt:
        return None

    # Handle strings
    if isinstance(dt, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
            try:
                dt = datetime.strptime(dt, fmt)
                break
            except ValueError:
                continue

    # Handle datetime
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt.astimezone(ZoneInfo("America/Sao_Paulo"))

    # Handle date
    if isinstance(dt, date):
        return dt

    return None


@app.context_processor
def url_helpers():
    def img_url(path, default_rel=None):
        p = (path or "").strip() or (default_rel or "")
        if p.startswith("/files/img/"):
            return p
        return url_for("static", filename=p)
    return {"img_url": img_url}

def _extract_securefile_id_from_url(url: str) -> Optional[int]:
    try:
        m = re.search(r"/files/img/(\d+)", (url or "").strip())
        return int(m.group(1)) if m else None
    except Exception:
        return None

def _delete_securefile_if_owned(file_id: int, user_id: int):
    try:
        sf = SecureFile.query.get(file_id)
        if sf and (sf.user_id is None or sf.user_id == user_id):
            db.session.delete(sf)
            db.session.commit()
    except Exception:
        db.session.rollback()

def get_logged_user() -> Optional[User]:
    uid = session.get('user_id')
    return User.query.get(uid) if uid else None

def login_required(f: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator de login que também valida trial / assinatura.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        u = get_logged_user()
        if not u:
            return redirect(url_for('login'))
        g.user = u

        # Admin bypass
        uname = (getattr(u, "username", "") or "").lower()
        if uname == "admin":
            return f(*args, **kwargs)

        # Get relevant fields
        now = datetime.utcnow()
        now_date = now.date()  # 👈 convert once for safe comparison
        trial_expiration = getattr(u, "trial_expiration", None)
        plan_status = getattr(u, "plan_status", None)
        plan_expires = getattr(u, "plan_expiration", None)

        # Paid users: allow if still valid
        if plan_status == "paid" and (
            plan_expires is None or plan_expires >= now
        ):
            return f(*args, **kwargs)

        # Trial users: compare dates only
        if trial_expiration and trial_expiration >= now_date:
            return f(*args, **kwargs)

        flash(
            "Seu período de teste de 14 dias expirou. Faça a assinatura para continuar usando o sistema.",
            "trial_expired"
        )
        return redirect(url_for('prices'))

    return wrapper

def current_user() -> User:
    u = getattr(g, "user", None) or get_logged_user()
    if not u:
        abort(401)
    return cast(User, u)

def basic_email(email: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email))

def user_exists(sess, username: Optional[str] = None, email: Optional[str] = None) -> Optional[str]:
    if username:
        if sess.execute(select(User.id).where(User.username == username)).scalar():
            return "username"
    if email:
        if sess.execute(select(User.id).where(User.email == email)).scalar():
            return "email"
    return None

@app.context_processor
def inject_user_context():
    u = getattr(g, "user", None) or get_logged_user()
    if not u:
        return {}
    return {
        "user": {
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "profile_image": (u.profile_image or DEFAULT_USER_IMAGE),
        }
    }

auth_bp = Blueprint('auth', __name__, template_folder='templates/auth')

# ------------------------------------------------------------------------------
# Cadastro com verificação de e-mail e suporte a plano (trial / mensal / anual)
# ------------------------------------------------------------------------------
@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        confirm = request.form.get('confirm') or ''
        plan = (request.form.get('plan') or '').strip()  # <- novo campo

        # 1️⃣ Validação de senha
        if len(password) < 8:
            return render_template("register.html",
                                   error_message="A senha deve ter pelo menos <strong>8 caracteres</strong>.")
        if not re.search(r"[A-Z]", password):
            return render_template("register.html",
                                   error_message="A senha deve conter pelo menos <strong>uma letra maiúscula</strong>.")
        if not re.search(r"\d", password):
            return render_template("register.html",
                                   error_message="A senha deve conter pelo menos <strong>um número</strong>.")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>_\-+=]", password):
            return render_template("register.html",
                                   error_message="A senha deve conter pelo menos <strong>um caractere especial</strong>.")

        # 2️⃣ Confirmação de senha
        if password != confirm:
            return render_template("register.html",
                                   error_message="As senhas não coincidem.")

        # 3️⃣ Verificar duplicações
        if not username:
            return render_template("register.html",
                                   error_message="Informe um <strong>nome de usuário</strong>.")

        if User.query.filter_by(username=username).first():
            return render_template("register.html",
                                   error_message="Este <strong>nome de usuário</strong> já está em uso.")

        existing_email = User.query.filter(func.lower(User.email) == email.lower()).first()
        if existing_email:
            return render_template("register.html",
                                   error_message="Este <strong>e-mail</strong> já está cadastrado.")

        # 4️⃣ Criar token de verificação
        s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        token = s.dumps(
            {
                'username': username,
                'email': email,
                'password_hash': generate_password_hash(password),
                'plan': plan  # <- incluímos o plano no token
            },
            salt='email-confirm'
        )

        confirm_url = url_for('auth.verify_email', token=token, _external=True)

        # 5️⃣ Enviar e-mail de verificação
        html = render_template(
            "emails/verify_account.html",
            username=username,
            confirm_url=confirm_url,
            current_year=datetime.utcnow().year
        )
        send_email(
            subject='Confirme sua conta - Ponza Health',
            recipients=[email],
            html=html,
            inline_images=[{
                "filename": "logo.png",
                "path": os.path.join("static", "images", "1.png"),
                "cid": "logo"
            }]
        )

        # 6️⃣ Mensagem de sucesso
        success_message = (
            "Cadastro realizado com sucesso! "
            f"Abra seu e-mail <strong>{email}</strong> e clique no link enviado para confirmar sua conta. "
            "Confira também a pasta SPAM."
        )
        return render_template("register.html", success_message=success_message)

    # GET
    return render_template("register.html")


# ------------------------------------------------------------------------------
# Verificação de e-mail (cria usuário e aciona Stripe se tiver plano)
# ------------------------------------------------------------------------------
@auth_bp.route('/verify_email/<token>')
def verify_email(token):
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        data = s.loads(token, salt='email-confirm', max_age=3600 * 24)
    except SignatureExpired:
        flash("O link de verificação expirou. Cadastre-se novamente.", "warning")
        return redirect(url_for('auth.register'))
    except BadSignature:
        abort(400)

    now = datetime.utcnow()
    plan = (data.get('plan') or '').strip().lower()

    # Evita duplicação: se o e-mail já foi confirmado antes
    existing_user = User.query.filter(func.lower(User.email) == data['email'].lower()).first()
    if existing_user:
        flash("Esta conta já foi confirmada anteriormente. Faça login.", "info")
        return redirect(url_for('login'))

    # Criação do novo usuário
    new_user = User(
        username=data['username'],
        email=data['email'].lower(),
        password_hash=data['password_hash'],
        created_at=now,
        plan_status='pending_payment' if plan else 'trial',
        trial_expiration=None if plan else now + timedelta(days=14),
        plan_expiration=None
    )
    db.session.add(new_user)
    db.session.commit()

    # Agendar e-mails do trial apenas se não houver plano
    if not plan:
        try:
            schedule_trial_emails(new_user.id)
        except Exception:
            current_app.logger.exception("Falha ao agendar e-mails de trial")

    # Se o usuário escolheu um plano (mensal/anual), envia direto pro Stripe
    if plan in ['monthly', 'yearly']:
        stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

        base_url = request.host_url.rstrip('/')
        price_amount = 958.80 if plan == 'yearly' else 89.90
        interval = 'year' if plan == 'yearly' else 'month'
        plan_name = f"Plano {'Anual' if plan == 'yearly' else 'Mensal'} Ponza Health"

        try:
            session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                mode='subscription',
                line_items=[{
                    'price_data': {
                        'currency': 'brl',
                        'unit_amount': int(price_amount * 100),
                        'product_data': {'name': plan_name},
                        'recurring': {'interval': interval}
                    },
                    'quantity': 1
                }],
                metadata={'user_id': str(new_user.id), 'plan': plan},
                success_url=f"{base_url}/subscription/success?session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{base_url}/planos"
            )
            # Redireciona para o checkout Stripe (nova aba / link)
            url = session.url or url_for("payments")
            return redirect(url, code=303)
        except Exception as e:
            current_app.logger.error(f"[Stripe] Erro ao criar sessão de checkout: {e}")
            flash("Erro ao iniciar pagamento. Tente novamente mais tarde.", "danger")
            return redirect(url_for('prices'))

    # Caso padrão: usuário sem plano → trial gratuito
    flash('Conta confirmada com sucesso! Você já pode fazer login.', 'success')
    return redirect(url_for('login'))


# ------------------------------------------------------------------------------
# Agendamento de e-mails de trial
# ------------------------------------------------------------------------------
def schedule_trial_emails(user_id: int) -> None:
    now = datetime.utcnow()
    offsets = [4, 7, 10, 14, 15]
    templates = ['trial_day4', 'trial_day7', 'trial_day10', 'trial_day14', 'trial_day15']

    for days, template in zip(offsets, templates):
        db.session.add(
            ScheduledEmail(
                user_id=user_id,
                template=template,
                send_at=now + timedelta(days=days)
            )
        )
    db.session.commit()


# ------------------------------------------------------------------------------
# Cron de envio de e-mails agendados
# ------------------------------------------------------------------------------
@auth_bp.route('/cron/dispatch_emails')
def dispatch_emails():
    key = request.args.get('key')
    if key != current_app.config.get('CRON_SECRET'):
        return 'Unauthorized', 403

    emails = (ScheduledEmail.query
              .filter(ScheduledEmail.sent.is_(False), #type:ignore
                      ScheduledEmail.send_at <= func.now())
              .all())

    sent_count = 0
    for e in emails:
        user = User.query.get(e.user_id)
        if not user:
            continue

        html = render_template(f'emails/{e.template}.html', user=user)
        send_email(
            subject='Aviso do período de teste',
            recipients=[user.email],
            html=html,
            inline_images=[{
                "filename": "logo.png",
                "path": os.path.join("static", "images", "1.png"),
                "cid": "logo"
            }]
        )
        e.sent = True
        sent_count += 1

    db.session.commit()
    return f'{sent_count} e-mails enviados.', 200
# Não esqueça de registrar o blueprint
app.register_blueprint(auth_bp)

# ------------------------------------------------------------------------------
# Páginas Públicas / Auth
# ------------------------------------------------------------------------------
@app.route('/')
def hero():
    return render_template("hero.html")

MIN_PASSWORD_LEN = 8

def _password_len_msg(pwd: str):
    return None if len(pwd) >= MIN_PASSWORD_LEN else (
        f"Senha muito curta — faltam <strong>{MIN_PASSWORD_LEN - len(pwd)}</strong> caractere(s) (mínimo {MIN_PASSWORD_LEN})."
    )

def _first(form, *keys, default=""):
    # pega o primeiro campo existente na requisição entre os nomes passados
    for k in keys:
        v = form.get(k)
        if v is not None:
            return v.strip()
    return default

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        login_input = (request.form.get('login') or '').strip()
        pwd         = request.form.get('password') or ''

        # busca por e-mail ou username (mantém fallback admin)
        if '@' in login_input:
            user = User.query.filter(func.lower(User.email) == login_input.lower()).first()
        else:
            user = User.query.filter(User.username == login_input).first()
            if not user and login_input.lower() == 'admin':
                user = User.query.filter(User.username == 'admin').first()

        stored_hash = getattr(user, 'password_hash', None) if user else None
        if not user or not stored_hash or not check_password_hash(stored_hash, pwd):
            flash('Usuário ou senha inválidos.', 'login_error')
            return redirect(url_for('login'))

        # sucesso de login com flash exclusivo
        session['user_id']  = user.id
        session['username'] = user.username
        return redirect(url_for('index'))

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/privacy_policy')
def privacy_policy():
    return render_template("privacy_policy.html")

@app.route('/termos')
def terms():
    return render_template("terms.html")

@app.route('/planos')
def prices():
    return render_template("prices.html")

@app.route('/about')
def about():
    return render_template("about.html")

@app.route('/centraldeajuda')
def help():
    return render_template("help.html")

# ------------------------------------------------------------------------------
# Dashboard
# ------------------------------------------------------------------------------
@app.route('/index')
@login_required
def index():
    u = current_user()

    # ---------------------------------------
    # Métricas gerais
    # ---------------------------------------
    total_patients = Patient.query.filter_by(user_id=u.id).count()
    total_consults = (
        Consult.query
        .join(Patient, Patient.id == Consult.patient_id)
        .filter(Patient.user_id == u.id)
        .count()
    )

    pkg = PackageUsage.query.filter_by(user_id=u.id).first()
    used = int(pkg.used) if pkg and pkg.used is not None else 0
    total = int(pkg.total) if pkg and pkg.total is not None else 0
    remaining = max(total - used, 0)

    # ---------------------------------------
    # Janelas de tempo
    # ---------------------------------------
    today = datetime.today().date()
    start_7 = today - timedelta(days=6)     # últimos 7 dias (inclui hoje)
    start_30 = today - timedelta(days=29)   # últimos 30 dias

    # ---------------------------------------
    # Consultas na última semana (Primeira x Retorno) via AgendaEvent.type
    # ---------------------------------------
    start_7d = today - timedelta(days=6)
    consults_week_series = []  # [{d:'dd/mm', primeira:int, retorno:int}]
    for i in range(7):
        day = start_7d + timedelta(days=i)
        day_start = datetime.combine(day, datetime.min.time())
        day_end   = datetime.combine(day, datetime.max.time())
        qday = (
            AgendaEvent.query
            .filter(
                AgendaEvent.user_id == u.id,
                AgendaEvent.start >= day_start,
                AgendaEvent.end   <= day_end
            )
        ).all()
        retorno = sum(1 for e in qday if (e.type or "").strip().lower() == "retorno")
        primeira = max(len(qday) - retorno, 0)
        consults_week_series.append({
            "d": day.strftime("%d/%m"),
            "primeira": int(primeira),
            "retorno": int(retorno),
        })

    # ---------------------------------------
    # Donut "Pacientes": Novos x Recorrentes (últimos 30 dias)
    # ---------------------------------------
    first_consult_q = (
        db.session.query(
            Consult.patient_id.label("pid"),
            func.min(Consult.date).label("first_date")
        )
        .join(Patient, Patient.id == Consult.patient_id)
        .filter(Patient.user_id == u.id)
        .group_by(Consult.patient_id)
        .all()
    )
    first_by_patient = {row.pid: row.first_date for row in first_consult_q}

    active_patients_30 = (
        db.session.query(Consult.patient_id)
        .join(Patient, Patient.id == Consult.patient_id)
        .filter(
            Patient.user_id == u.id,
            Consult.date >= start_30,
            Consult.date <= today
        )
        .distinct()
        .all()
    )
    pids_30 = [r.patient_id for r in active_patients_30]

    patients_new_30 = 0
    patients_return_30 = 0
    for pid in pids_30:
        f = first_by_patient.get(pid)
        if f is None:
            continue
        if f >= start_30:
            patients_new_30 += 1
        else:
            patients_return_30 += 1

    # Sexo
    male_aliases = {"m", "masculino", "homem", "male"}
    female_aliases = {"f", "feminino", "mulher", "female"}

    patients_30_objs = (
        Patient.query
        .filter(Patient.user_id == u.id)
        .all()
    )
    male_count = sum(1 for p in patients_30_objs if (p.sex or "").strip().lower() in male_aliases)
    female_count = sum(1 for p in patients_30_objs if (p.sex or "").strip().lower() in female_aliases)

    # Procedimentos 30 dias
    events_30 = (
        AgendaEvent.query
        .filter(
            AgendaEvent.user_id == u.id,
            AgendaEvent.start >= datetime.combine(start_30, datetime.min.time()),
            AgendaEvent.start <= datetime.combine(today, datetime.max.time()),
        )
        .all()
    )
    procedures_return_30 = sum(1 for e in events_30 if (e.type or "").lower() == "retorno")
    procedures_first_30 = sum(1 for e in events_30 if (e.type or "").lower() != "retorno")

    # Convênio 30 dias
    insurance_particular_30 = sum(1 for e in events_30 if (e.billing or "").lower() == "particular")
    insurance_convenio_30   = sum(1 for e in events_30 if (e.billing or "").lower() == "convenio")

    # Estoque baixo
    try:
        low_stock_qs = (
            Product.query
            .filter(Product.user_id == u.id)
            .filter(Product.quantity < 5)
            .order_by(Product.quantity.asc(), Product.name.asc())
            .all()
        )
        low_stock = [{"name": p.name, "quantity": (p.quantity or 0)} for p in low_stock_qs]
    except Exception as e:
        print("[INDEX] low_stock error:", e)
        low_stock = []

    # Cotações
    quotes_items = []
    quotes_total = 0
    quotes_responded = 0
    quotes_pending = 0

    try:
        base = Quote.query
        col_user_id = getattr(Quote, "user_id", None)

        if col_user_id is not None:
            base = base.filter(col_user_id == u.id)

        try:
            quotes_list = base.order_by(Quote.created_at.desc()).all()
        except Exception:
            quotes_list = base.all()

        quotes_total = len(quotes_list)

        responses_by_quote_id = {}
        used_strategy = None

        # QuoteResponse?
        try:
            from models import QuoteResponse  # type: ignore
            rows = (
                db.session.query(QuoteResponse.quote_id, func.count(QuoteResponse.id))
                .group_by(QuoteResponse.quote_id)
                .all()
            )
            responses_by_quote_id = {qid: int(cnt) for qid, cnt in rows if qid is not None}
            used_strategy = "QuoteResponse"
        except Exception:
            pass

        # status na Quote
        if used_strategy is None:
            try:
                responded_status = {"respondida", "respondido", "finalizada", "fechada", "responded"}
                for q in quotes_list:
                    status_val = (getattr(q, "status", "") or "").strip().lower()
                    responses_by_quote_id[getattr(q, "id", None)] = 1 if status_val in responded_status else 0
                used_strategy = "status"
            except Exception:
                pass

        # campo "responses"
        if used_strategy is None:
            for q in quotes_list:
                cnt = 0
                try:
                    val = getattr(q, "responses", None)
                    if val:
                        if isinstance(val, (list, tuple)):
                            cnt = len(val)
                        elif isinstance(val, dict):
                            cnt = len(val.keys())
                        elif isinstance(val, str):
                            s = val.strip()
                            cnt = 0 if s in ("", "[]", "{}") else 1
                        else:
                            cnt = 1
                except Exception:
                    cnt = 0
                responses_by_quote_id[getattr(q, "id", None)] = int(cnt)

        for q in quotes_list:
            qid = getattr(q, "id", None)
            title = getattr(q, "title", None) or getattr(q, "name", None) or f"Cotação #{qid or ''}"
            resp_count = int(responses_by_quote_id.get(qid, 0))
            quotes_items.append({"name": title, "responses": resp_count})

        quotes_responded = sum(1 for it in quotes_items if it["responses"] > 0)
        quotes_pending = max(quotes_total - quotes_responded, 0)

    except Exception as e:
        print("[INDEX] quotes stats/table error:", e)

    # Render
    return render_template(
        'index.html',
        total_patients=total_patients,
        total_consults=total_consults,
        used=used,
        remaining=remaining,
        package_used=used,
        package_limit=total,
        package_total=total,
        consults_week_series=consults_week_series,
        patients_new_30=patients_new_30,
        patients_return_30=patients_return_30,
        male_count=male_count,
        female_count=female_count,
        procedures_return_30=procedures_return_30,
        procedures_first_30=procedures_first_30,
        insurance_particular_30=insurance_particular_30,
        insurance_convenio_30=insurance_convenio_30,
        low_stock=low_stock,
        quotes_total=quotes_total,
        quotes_responded=quotes_responded,
        quotes_pending=quotes_pending,
        quotes_items=quotes_items,
        notifications_unread=0,
        trial_active = (u.trial_expiration and u.trial_expiration >= datetime.utcnow().date())

    )

# ------------------------------------------------------------------------------
# Compra de Pacotes
# ------------------------------------------------------------------------------
@app.route('/purchase', methods=['GET', 'POST'])
@login_required
def purchase():
    """
    Página de compra de pacotes de análises (Stripe Checkout).
    Se for GET, mostra a página.
    Se for POST, cria uma sessão de pagamento Stripe e redireciona o usuário.
    """
    if request.method == 'POST':
        pacote = request.form.get('package', '')
        price_map = {
            '50': STRIPE_PRICE_PACKAGE_50,
            '150': STRIPE_PRICE_PACKAGE_150,
            '500': STRIPE_PRICE_PACKAGE_500,
        }
        price_id = price_map.get(pacote)

        if not price_id:
            flash('Selecione um pacote válido.', 'warning')
            return redirect(url_for('payments'))

        try:
            session = stripe.checkout.Session.create(
                mode='payment',
                payment_method_types=['card'],
                line_items=[{'price': price_id, 'quantity': 1}],
                success_url=f"{url_for('payments', _external=True)}?success=true",
                cancel_url=f"{url_for('payments', _external=True)}?canceled=true",
            )
            print(f"[Stripe] ✅ Sessão criada para pacote {pacote}")
            return redirect(session.url or url_for('payments'), code=303)

        except Exception as e:
            print("[Stripe] ❌ Erro ao criar sessão:", e)
            flash("Erro ao iniciar pagamento. Tente novamente mais tarde.", "danger")
            return redirect(url_for('payments'))

    # Se for GET, só renderiza a página
    return render_template('purchase.html', notifications_unread=0)


@app.route('/payments', methods=['GET'])
@login_required
def payments():
    """
    Página única que permite:
    - Comprar pacotes de análises
    - Assinar plano mensal
    """
    return render_template('purchase.html', notifications_unread=0)

# ------------------------------------------------------------------------------
# Conta
# ------------------------------------------------------------------------------
@app.route('/account')
@login_required
def account():
    """
    Página da conta: mostra status do plano, dias restantes do trial e botão para assinar.
    """
    u = current_user()
    now = datetime.utcnow()

    # calcular dados do trial
    trial_expiration = getattr(u, "trial_expiration", None)
    if trial_expiration:
        remaining_td = trial_expiration - now.date()
        remaining_days = max(0, remaining_td.days)
        trial_active = (trial_expiration >= now.date())
    else:
        remaining_days = 0
        trial_active = False

    # status pago?
    plan_status = getattr(u, "plan_status", None) or "inactive"
    plan_expiration = getattr(u, "plan_expiration", None)
    is_paid_active = False
    if plan_status == "paid":
        if (plan_expiration is None) or (plan_expiration and plan_expiration >= now):
            is_paid_active = True

    # admin bypass
    is_admin = (getattr(u, "username", "").lower() == "admin")

    return render_template(
        'account.html',
        user=u,
        trial_active=trial_active,
        trial_remaining_days=remaining_days,
        plan_status=plan_status,
        plan_expiration=plan_expiration,
        is_paid_active=is_paid_active,
        is_admin=is_admin
    )

@app.route('/subscribe', methods=['GET', 'POST'])
@login_required
def subscribe():
    """
    Fluxo simples de assinatura:
      - GET: mostra página de preços (ou redireciona para /planos)
      - POST: marca usuário como 'paid' e define plan_expiration = agora + 30 dias
    Observação: aqui é o lugar para integrar MercadoPago / Stripe / gateway real.
    """
    u = current_user()
    now = datetime.utcnow()

    # Se vier POST -> "confirmar pagamento" (simulação)
    if request.method == "POST":
        # Simulação: marcar como pago por 30 dias
        u.plan_status = "paid"
        u.plan_expiration = now + timedelta(days=30)
        # remover trial (opcional)
        u.trial_expiration = None
        db.session.commit()
        flash("Pagamento registrado. Obrigado! Sua assinatura foi ativada por 30 dias.", "success")
        return redirect(url_for('account'))

    # GET -> renderizar a página de preços / checkout
    # Se já está pago, redireciona para a conta
    if (u.plan_status == "paid") and (not u.plan_expiration or u.plan_expiration >= now):
        flash("Sua assinatura já está ativa.", "info")
        return redirect(url_for('account'))

    # renderiza a página de preços (ou template de checkout)
    return render_template('prices.html')

# ------------------------------------------------------------------------------
# Stripe Subscription Integration
# ------------------------------------------------------------------------------
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

STRIPE_PRICE_MONTHLY = os.getenv("STRIPE_PRICE_MONTHLY", "")
STRIPE_PRICE_YEARLY = os.getenv("STRIPE_PRICE_YEARLY", "")
STRIPE_PRICE_PACKAGE_50 = os.getenv("STRIPE_PRICE_PACKAGE_50", "")
STRIPE_PRICE_PACKAGE_150 = os.getenv("STRIPE_PRICE_PACKAGE_150", "")
STRIPE_PRICE_PACKAGE_500 = os.getenv("STRIPE_PRICE_PACKAGE_500", "")

@app.route("/subscribe_pay_mensal")
@login_required
def subscribe_pay_mensal():
    """Gera link de pagamento do Stripe para o plano mensal (R$ 89,90)."""
    user = current_user()
    session = stripe.checkout.Session.create(
        mode="subscription",
        payment_method_types=["card"],
        line_items=[{"price": STRIPE_PRICE_MONTHLY, "quantity": 1}],
        metadata={"user_id": str(user.id), "plan": "monthly"},
        success_url=f"{url_for('subscription_success', _external=True)}?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{url_for('payments', _external=True)}?canceled=true",
    )
    print("[Stripe] ✅ Sessão criada: plano mensal")
    url = session.url or url_for("payments")
    return redirect(url, code=303)

@app.route("/subscribe_pay_anual")
@login_required
def subscribe_pay_anual():
    """Gera link de pagamento do Stripe para o plano anual (R$ 958,80)."""
    user = current_user()
    session = stripe.checkout.Session.create(
        mode="subscription",
        payment_method_types=["card"],
        line_items=[{"price": STRIPE_PRICE_YEARLY, "quantity": 1}],
        metadata={"user_id": str(user.id), "plan": "yearly"},
        success_url=f"{url_for('subscription_success', _external=True)}?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{url_for('payments', _external=True)}?canceled=true",
    )
    print("[Stripe] ✅ Sessão criada: plano anual")
    url = session.url or url_for("payments")
    return redirect(url, code=303)
        
@app.route("/purchase_package/<int:package>")
@login_required
def purchase_package(package):
    """Cria link de checkout Stripe para os pacotes de análises (50, 150, 500)."""
    price_map = {
        50: STRIPE_PRICE_PACKAGE_50,
        150: STRIPE_PRICE_PACKAGE_150,
        500: STRIPE_PRICE_PACKAGE_500,
    }
    price_id = price_map.get(package)
    if not price_id:
        flash("Pacote inválido.", "danger")
        return redirect(url_for("payments"))

    session = stripe.checkout.Session.create(
        mode="payment",
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{url_for('payments', _external=True)}?success=true",
        cancel_url=f"{url_for('payments', _external=True)}?canceled=true",
    )
    print(f"[Stripe] ✅ Sessão criada: pacote {package}")
    url = session.url or url_for("payments")
    return redirect(url, code=303)

@app.route('/stripe/webhook', methods=['POST'])
def stripe_webhook():
    """Recebe notificações do Stripe (pagamento confirmado)."""
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')
    endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except ValueError:
        return "Invalid payload", 400
    except stripe.error.SignatureVerificationError:  # type: ignore
        return "Invalid signature", 400

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        user_id = session.get('metadata', {}).get('user_id')
        plan = session.get('metadata', {}).get('plan', 'monthly')

        from datetime import timedelta
        user = User.query.get(int(user_id)) if user_id else None
        if user:
            user.plan_status = 'paid'
            user.trial_expiration = None
            if plan == 'yearly':
                user.plan_expiration = datetime.utcnow() + timedelta(days=365)
            else:
                user.plan_expiration = datetime.utcnow() + timedelta(days=30)
            db.session.commit()
            print(f"[Stripe] Plano {plan} ativado para o usuário {user.email}")
    return jsonify(success=True)


@app.route('/subscription/success')
def subscription_success():
    user_id = request.args.get('metadata[user_id]')
    if user_id:
        user = User.query.get(int(user_id))
        if user:
            user.plan_status = 'paid'
            user.plan_expiration = datetime.utcnow() + timedelta(days=30)
            user.trial_expiration = None
            db.session.commit()
    flash("Assinatura ativada por 30 dias.", "success")
    return redirect(url_for('account'))

@app.route("/cancel_subscription", methods=["POST"])
@login_required
def cancel_subscription():
    """
    Cancela a assinatura do usuário no Stripe.
    """
    try:
        stripe.Subscription.delete(current_user.subscription_id)
        flash("Assinatura cancelada com sucesso.", "success")
    except Exception as e:
        print("[Stripe] ❌ Erro ao cancelar:", e)
        flash("Erro ao cancelar a assinatura.", "danger")
    return redirect(url_for("account"))


@app.route('/remove_profile_image', methods=['POST'], endpoint='remove_profile_image')
@login_required
def remove_profile_image():
    u = current_user()

    # Se a imagem atual for um SecureFile, remove
    current = (u.profile_image or "").replace("\\", "/")
    sid = _extract_securefile_id_from_url(current)
    if sid:
        _delete_securefile_if_owned(sid, u.id)

    u.profile_image = DEFAULT_USER_IMAGE
    db.session.commit()
    flash("Foto de perfil removida.", "info")
    return redirect(url_for("account"))

@app.route('/update_personal_info', methods=['POST'], endpoint='update_personal_info')
@login_required
def update_personal_info():
    from datetime import datetime as _dt
    import time as _time

    u = current_user()

    name = (request.form.get("name") or "").strip()
    clinic_phone = (request.form.get("clinic_phone") or "").strip()
    birthdate_str = (request.form.get("birthdate") or "").strip()
    email = (request.form.get("email") or "").strip().lower()

    if name:
        u.name = name

    if clinic_phone:
        u.clinic_phone = clinic_phone

    if email:
        u.email = email

    if birthdate_str:
        try:
            u.birthdate = _dt.strptime(birthdate_str, "%Y-%m-%d").date()
        except ValueError:
            flash("Data de nascimento inválida. Use o formato AAAA-MM-DD.", "warning")

    file = request.files.get("profile_image")
    if file and file.filename:
        if not allowed_file(file.filename):
            flash("Tipo de arquivo não permitido. Use png, jpg ou jpeg.", "warning")
            return redirect(url_for("account"))

        filename = secure_filename(file.filename)
        ext = filename.rsplit(".", 1)[1].lower()
        if ext not in {"png", "jpg", "jpeg"}:
            flash("Tipo de arquivo não permitido. Use png, jpg ou jpeg.", "warning")
            return redirect(url_for("account"))

        content = file.read()
        if not content:
            flash("Arquivo de imagem inválido.", "warning")
            return redirect(url_for("account"))

        old = (u.profile_image or "").replace("\\", "/")
        old_sid = _extract_securefile_id_from_url(old)
        if old_sid:
            _delete_securefile_if_owned(old_sid, u.id)

        new_name = f"user_{u.id}_{int(_time.time())}.{ext}"
        sf = SecureFile(
            user_id=u.id,
            kind="profile_image",
            filename=new_name,
            mime_type=file.mimetype or f"image/{ext}",
            size_bytes=len(content),
            data=content,
        )
        db.session.add(sf)
        db.session.flush()
        u.profile_image = f"/files/img/{sf.id}"

    db.session.commit()
    flash("Dados pessoais atualizados com sucesso!", "success")
    return redirect(url_for("account"))

@app.route('/update_password', methods=['POST'])
@login_required
def update_password():
    u = current_user()
    cur  = request.form.get("current_password", "")
    new  = request.form.get("new_password", "")
    conf = request.form.get("confirm_password", "")

    stored_hash = getattr(u, 'password_hash', None) or getattr(u, 'password', None)
    if not stored_hash or not check_password_hash(stored_hash, cur):
        flash("Senha atual incorreta.", "warning")
        return redirect(url_for("account"))

    if new != conf:
        flash("As senhas não coincidem.", "warning")
        return redirect(url_for("account"))

    u.password_hash = generate_password_hash(new)
    db.session.commit()
    flash("Senha atualizada com sucesso!", "success")
    return redirect(url_for("account"))

# ------------------------------------------------------------------------------
# Upload / Prescrição
# ------------------------------------------------------------------------------

def _project_references_json() -> str:
    """
    Return an existing references.json path. We look in common safe locations:
    - instance/references.json           (recommended; already writable)
    - <project root>/references.json
    - <project root>/static/references.json
    - <project root>/data/references.json
    """
    candidates = [
        os.path.join(BASE_DIR, "references.json"),
        os.path.join(app.root_path, "references.json"),
        os.path.join(STATIC_DIR, "references.json"),
        os.path.join(app.root_path, "data", "references.json"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    raise FileNotFoundError(
        "references.json not found. Place it in 'instance/' or the project root."
    )

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    """
    Upload de exames ou entrada manual de resultados.
    - GET: exibe o formulário
    - POST: processa dados manuais OU arquivo PDF
    """
    from prescription import analyze_pdf

    u = current_user()

    if request.method == 'GET':
        return render_template(
            'upload.html',
            success=request.args.get('success', type=int),
            success_id=request.args.get('success_id', type=int),
            error=request.args.get('error'),
            notifications_unread=0
        )

    # ==========================================================
    # ENTRADA MANUAL
    # ==========================================================
    if request.form.get('manual_entry') == '1':
        return _handle_manual_entry(request, u, analyze_pdf)

    # ==========================================================
    # UPLOAD DE PDF
    # ==========================================================
    return _handle_pdf_upload(request, u, analyze_pdf)


# =====================================================================
# Helpers internos para manter a rota enxuta
# =====================================================================

def _handle_manual_entry(request, u, analyze_pdf):
    """Processa inserção manual de resultados."""
    name          = (request.form.get('name') or '').strip()
    age           = (request.form.get('age') or '').strip()
    cpf           = (request.form.get('cpf') or '').strip()
    gender        = (request.form.get('gender') or '').strip()
    phone         = (request.form.get('phone') or '').strip()
    doctor_name   = (request.form.get('doctor') or '').strip()
    doctor_phone  = (request.form.get('doctor_phone') or '').strip()
    patient_name  = (request.form.get('patient_name') or '').strip()
    patient_phone = (request.form.get('patient_phone') or '').strip()
    lab_results   = (request.form.get('lab_results') or '').strip()

    send_doctor  = request.form.get('send_doctor') == '1'
    send_patient = request.form.get('send_patient') == '1'

    if not lab_results:
        return redirect(url_for('upload', error="Digite os resultados no campo de texto."))

    refs_path = _project_references_json()
    dgn, rx, *_ = analyze_pdf(lab_results, references_path=refs_path, manual=True)

    p = _get_or_create_patient(u, name=name, cpf=cpf, gender=gender, phone=phone)
    if doctor_name:
        _assign_doctor_to_patient(u, p, doctor_name)
    _attach_consult_and_notes(p, dgn, rx)

    clinic_contact = (u.clinic_phone or u.name or u.username or '').strip() or '-'

    if send_doctor and doctor_phone:
        send_pdf_whatsapp_template(
            "relatorio_ponza",
            doctor_name,
            p.name,
            doctor_phone,
            p.id,
            clinic_contact=clinic_contact,
        )

    if send_patient and patient_phone:
        send_pdf_whatsapp_patient(
            patient_name or p.name,
            patient_phone,
            p.id,
            clinic_phone=u.clinic_phone
        )

    return redirect(url_for('result', patient_id=p.id))

def _handle_pdf_upload(request, u, analyze_pdf):
    """Processa upload de arquivo PDF, analisa e envia relatórios via WhatsApp."""
    import tempfile
    from prescription import send_pdf_whatsapp_template, send_pdf_whatsapp_patient

    file = request.files.get('pdf_file')
    if not file or not file.filename.lower().endswith('.pdf'):
        return redirect(url_for('upload', error="Nenhum PDF válido enviado."))

    content = file.read()
    if not content:
        return redirect(url_for('upload', error="PDF vazio ou inválido."))

    sf = SecureFile(
        user_id=u.id,
        kind="upload_pdf",
        filename=secure_filename(file.filename),
        mime_type="application/pdf",
        size_bytes=len(content),
        data=content
    )
    db.session.add(sf)
    db.session.flush()

    pf = PdfFile(
        filename=sf.filename,
        original_name=file.filename,
        size_bytes=sf.size_bytes,
        secure_file_id=sf.id
    )
    db.session.add(pf)
    db.session.commit()

    refs_path = _project_references_json()
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".pdf")
    with os.fdopen(fd, "wb") as fh:
        fh.write(content)

    dgn, rx, name_ai, gender_ai, age_ai, cpf_ai, phone_ai, doctor_ai, birth_ai = analyze_pdf(tmp, references_path=refs_path, manual=False)
    os.remove(tmp)

    p = _get_or_create_patient(
        u,
        name=name_ai,
        cpf=(cpf_ai or '').strip(),
        gender=gender_ai,
        phone=phone_ai,
        birthdate=birth_ai,
    )

    if doctor_ai:
        _assign_doctor_to_patient(u, p, doctor_ai)

    notes_blob = _attach_consult_and_notes(p, dgn, rx)
    pf.patient_id = p.id
    db.session.commit()

    send_doctor  = request.form.get('send_doctor') == '1'
    send_patient = request.form.get('send_patient') == '1'

    doctor_name   = (request.form.get('doctor_name') or '').strip()
    doctor_phone  = (request.form.get('doctor_phone') or '').strip()
    patient_name  = (request.form.get('patient_name') or '').strip()
    patient_phone = (request.form.get('patient_phone') or '').strip()

    clinic_contact = (u.clinic_phone or u.name or u.username or '').strip() or '-'

    if send_doctor and doctor_phone:
        send_pdf_whatsapp_template(
            "relatorio_ponza",
            doctor_name,
            p.name,
            doctor_phone,
            p.id,
            clinic_contact=clinic_contact,
        )

    if send_patient and patient_phone:
        send_pdf_whatsapp_patient(
            patient_name or p.name,
            patient_phone,
            p.id,
            clinic_phone=u.clinic_phone
        )

    return redirect(url_for('result', patient_id=p.id))

def _parse_birthdate(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(candidate, fmt).date()
        except Exception:
            continue
    return None

def _normalize_gender_label(gender: Optional[str]) -> Optional[str]:
    if not gender:
        return None
    token = gender.strip()
    if not token:
        return None
    upper = token.upper()
    if upper in {"F", "FEMININO", "FEMALE"}:
        return "Feminino"
    if upper in {"M", "MASCULINO", "MALE"}:
        return "Masculino"
    return token.title()

def _parse_doctor_text(doctor_text: Optional[str]) -> tuple[str, str, str]:
    if not doctor_text:
        return "", "", ""
    raw = doctor_text.strip()
    if not raw:
        return "", "", ""
    match = re.search(r"(?i)(crm|crf)(?:[-\s]?([A-Z]{2}))?[\s#:]*([0-9][0-9.\s]*)", raw)
    name_part = raw
    if match:
        name_part = raw[:match.start()]
    name_clean = re.sub(r"[\s\-,:]+$", "", name_part).strip()
    name_clean = re.sub(r"(?i)^(dr\.?|dra\.?)\s+", "", name_clean)
    name_clean = re.sub(r"\s+", " ", name_clean).strip()
    cred_label = ""
    cred_digits = ""
    if match:
        cred_label = match.group(1).upper()
        if match.group(2):
            cred_label = f"{cred_label}-{match.group(2).upper()}"
        cred_digits = re.sub(r"\D", "", match.group(3) or "")
    return name_clean, cred_label, cred_digits

def _assign_doctor_to_patient(user, patient, doctor_text: Optional[str]):
    name, cred_label, cred_digits = _parse_doctor_text(doctor_text)
    if not name:
        return None

    display_name = name
    cred_value = " ".join(part for part in (cred_label, cred_digits) if part).strip()

    query = Doctor.query
    if hasattr(Doctor, "user_id"):
        query = query.filter(Doctor.user_id == user.id)

    doctor = None
    if cred_value:
        doctor = query.filter(func.lower(Doctor.crm) == cred_value.lower()).first()
    if not doctor:
        doctor = query.filter(func.lower(Doctor.name) == display_name.lower()).first()

    if not doctor:
        doctor = Doctor(
            user_id=user.id if hasattr(Doctor, "user_id") else None,
            name=display_name,
            crm=cred_value or None,
        )
        db.session.add(doctor)
        db.session.flush()
    else:
        updated = False
        if doctor.name.strip() != display_name:
            doctor.name = display_name
            updated = True
        normalized_crm = (doctor.crm or "").strip()
        if cred_value and normalized_crm.lower() != cred_value.lower():
            doctor.crm = cred_value
            updated = True
        if updated:
            db.session.add(doctor)

    if patient.doctor_id != doctor.id:
        patient.doctor = doctor
        db.session.add(patient)

    return doctor

def _get_or_create_patient(u, *, name=None, cpf=None, gender=None, phone=None, birthdate=None):
    p = None
    if cpf:
        p = Patient.query.filter_by(user_id=u.id, cpf=cpf).first()
    if not p and name:
        p = Patient.query.filter_by(user_id=u.id, name=name).first()
    if not p:
        p = Patient(
            user_id=u.id,
            name=name or f"Paciente ({datetime.now():%d/%m/%Y %H:%M})",
            sex=_normalize_gender_label(gender) or None,
            cpf=cpf or None,
            birthdate=_parse_birthdate(birthdate),
            phone_primary=normalize_phone(phone) if phone else '',
            notes=None,
            profile_image=DEFAULT_PATIENT_IMAGE
        )
        db.session.add(p)
        db.session.commit()
        return p

    updated = False
    if name:
        candidate = name.strip()
        if candidate and (not p.name or p.name.startswith("Paciente (") or len(candidate) > len(p.name) or p.name.lower() != candidate.lower()):
            p.name = candidate
            updated = True

    gender_norm = _normalize_gender_label(gender)
    if gender_norm and (p.sex or '').lower() != gender_norm.lower():
        p.sex = gender_norm
        updated = True

    birth_dt = _parse_birthdate(birthdate)
    if birth_dt and p.birthdate != birth_dt:
        p.birthdate = birth_dt
        updated = True

    if cpf and (p.cpf or '').strip() != cpf.strip():
        p.cpf = cpf.strip()
        updated = True

    if phone:
        normalized_phone = normalize_phone(phone)
        if normalized_phone and (p.phone_primary or '').strip() != normalized_phone:
            p.phone_primary = normalized_phone
            updated = True

    if updated:
        db.session.add(p)
        db.session.commit()
    return p

# ------------------------------------------------------------------------------
# Resultados (HTML e PDF)
# ------------------------------------------------------------------------------

def _attach_consult_and_notes(p, dgn, rx):
    """Cria consulta e anexa diagnóstico/prescrição ao paciente."""
    notes_blob = (dgn or '') + "\n\nPrescrição:\n" + (rx or '')
    p.notes = (p.notes or '') + "\n\n" + notes_blob if p.notes else notes_blob
    db.session.add(Consult(patient_id=p.id, date=datetime.today().date(), notes=notes_blob))
    db.session.commit()
    return notes_blob

@app.route('/patient_result/<int:patient_id>')
@login_required
def patient_result(patient_id):
    u = current_user()
    patient = Patient.query.get_or_404(patient_id)
    if patient.user_id != u.id:
        abort(403)

    consult = (
        Consult.query
        .filter_by(patient_id=patient_id)
        .order_by(Consult.date.desc())
        .first()
    )

    notes = consult.notes if consult else ""
    diagnosis, prescription = "", ""
    if "Prescrição:" in notes:
        parts = notes.split("Prescrição:", 1)
        diagnosis = parts[0].strip()
        prescription = parts[1].strip()

    return render_template(
        'result.html',
        patient=patient,
        diagnostic_text=diagnosis,
        prescription_text=prescription,
        notifications_unread=0,
    )

@app.route('/download_pdf/<int:patient_id>')
@login_required
def download_pdf(patient_id):
    """
    Gera e faz download do PDF de resultados do paciente (com dados e assinatura).
    """
    from weasyprint import HTML
    from flask import send_file
    import tempfile
    import re
    import io

    # === Usuário atual ===
    u = current_user()

    # Usa o método moderno do SQLAlchemy 2.0
    patient = db.session.get(Patient, patient_id)
    if not patient:
        abort(404)

    if patient.user_id != u.id:
        abort(403)

    # Última consulta e diagnóstico/prescrição
    consult = (
        db.session.query(Consult)
        .filter_by(patient_id=patient_id)
        .order_by(Consult.date.desc())
        .first()
    )

    notes = consult.notes if consult else ""
    diagnosis, prescription = "", ""
    if notes:
        split_key = None
        for key in ["Prescrição:", "Prescricao:", "Prescrição\n", "Prescricao\n"]:
            if key in notes:
                split_key = key
                break

        if split_key:
            parts = notes.split(split_key, 1)
            diagnosis = parts[0].strip()
            prescription = parts[1].strip() if len(parts) > 1 else ""
        else:
            diagnosis = notes.strip()
            prescription = ""

    # === Cálculo da idade ===
    def _calc_age(birthdate):
        try:
            today = datetime.today().date()
            return today.year - birthdate.year - ((today.month, today.day) < (birthdate.month, birthdate.day))
        except Exception:
            return None

    age_str = ""
    if getattr(patient, "birthdate", None):
        age_val = _calc_age(patient.birthdate)
        if age_val is not None:
            age_str = f"{age_val} anos"

    # === Dados básicos do paciente ===
    sex_str = (patient.sex or "").strip()
    cpf_str = (patient.cpf or "").strip()
    phones = [x for x in [(patient.phone_primary or "").strip(), (patient.phone_secondary or "").strip()] if x]
    phone_str = " / ".join(phones)

    patient_info = [
        f"Nome: {patient.name or '—'}",
        f"Data de nascimento: {patient.birthdate.strftime('%d/%m/%Y') if patient.birthdate else '—'}",
    ]
    if age_str:
        patient_info.append(f"Idade: {age_str}")
    if sex_str:
        patient_info.append(f"Sexo: {sex_str}")
    if cpf_str:
        patient_info.append(f"CPF: {cpf_str}")
    if phone_str:
        patient_info.append(f"Telefone: {phone_str}")

    public_base = current_app.config.get("PUBLIC_BASE_URL")
    if public_base:
        base = public_base.rstrip("/")
        logo_url = f"{base}/static/images/1.png"
    elif request:
        logo_url = url_for("static", filename="images/1.png", _external=True)
    else:
        logo_url = os.path.join(current_app.root_path, "static", "images", "1.png")
    html_str = render_template(
        "result_pdf.html",
        patient_info="\n".join(patient_info),
        diagnostic_text=diagnosis,
        prescription_text=prescription,
        doctor_name=(getattr(u, "name", None) or u.username),
        logo_url=logo_url,
    )

    # === Gera PDF ===
    pdf_io = io.BytesIO()
    HTML(string=html_str, base_url=current_app.root_path).write_pdf(pdf_io)
    pdf_io.seek(0)

    # === Salva PDF no banco ===
    try:
        pdf_bytes = pdf_io.getvalue()
        display_name = f"Resultado_{(patient.name or 'Paciente').replace(' ', '_')}.pdf"
        consult_id = consult.id if consult else None

        _save_pdf_bytes_to_db(
            user_id=u.id,
            patient_id=patient.id,
            consult_id=consult_id,
            original_name=display_name,
            data=pdf_bytes,
            kind="result_pdf",
        )
    except Exception as e:
        db.session.rollback()
        print("[PDF] erro ao salvar PDF gerado no DB:", e)

    # === Envia PDF ao usuário ===
    download_name = f"Resultado_{(patient.name or 'Paciente').replace(' ', '_')}.pdf"

    # ✅ Sanitize filename to prevent newline or carriage return issues
    download_name = re.sub(r'[\r\n]+', '', download_name).strip()

    pdf_io.seek(0)
    return send_file(
        pdf_io,
        as_attachment=True,
        download_name=download_name,
        mimetype="application/pdf"
    )

@app.route('/public_download')
def public_download():
    token = request.args.get('token')
    if not token:
        abort(400)
    try:
        s = URLSafeSerializer(app.config['SECRET_KEY'])
        patient_id = s.loads(token)
    except Exception:
        abort(403)

    pdf = PdfFile.query.filter_by(patient_id=patient_id).order_by(PdfFile.id.desc()).first()
    if not pdf or not pdf.secure_file:
        abort(404)

    binary = getattr(pdf.secure_file, "data", None)
    if binary is None:
        abort(404)

    return send_file(
        io.BytesIO(binary),
        mimetype="application/pdf",
        as_attachment=False,
        download_name=f"relatorio_{patient_id}.pdf"
    )

@app.route('/result/<int:patient_id>')
@login_required
def result(patient_id):
    """Alias compatível para patient_result (mantém links antigos funcionando)."""
    return redirect(url_for('patient_result', patient_id=patient_id))

# ------------------------------------------------------------------------------
# Agenda (tela)
# ------------------------------------------------------------------------------
@app.route('/agenda', methods=['GET'], endpoint='agenda')
@login_required
def agenda_view():
    try:
        return render_template('agenda.html')
    except TemplateNotFound:
        return """
        <!doctype html><meta charset="utf-8">
        <h1>Agenda</h1>
        <p>Crie o template <code>templates/agenda.html</code>.</p>
        <p><a href="{0}">Voltar</a></p>
        """.format(url_for('index'))

# ------------------------------------------------------------------------------
# Agenda (API)  ✅ corrigida p/ ISO com 'Z' e DELETE
# ------------------------------------------------------------------------------

def _parse_iso_to_naive_utc(s: str) -> Optional[datetime]:
    """
    Converte strings ISO8601 (inclui casos com 'Z' e offsets) para datetime naive em UTC.
    Retorna None se não conseguir parsear.
    """
    s = (s or "").strip()
    if not s:
        return None
    # normaliza 'Z' -> '+00:00'
    s = s.replace("Z", "+00:00")
    # normaliza timezone sem ':' no final (ex: +0300 -> +03:00)
    if re.match(r".*[+-]\d{4}$", s):
        s = s[:-2] + ":" + s[-2:]
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        return None
    # converte para UTC e remove tzinfo (naive)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


@app.route('/api/events', methods=['GET'])
@login_required
def api_events():
    """
    Retorna eventos do usuário. Aceita ?start=...&end=... do FullCalendar.
    Também inclui Consult (somente leitura), que não possuem id/editable.
    """
    u = current_user()
    start_q = request.args.get('start')  # FC manda algo como 2025-09-01T00:00:00Z
    end_q   = request.args.get('end')

    start_dt = _parse_iso_to_naive_utc(start_q) if start_q else None
    end_dt   = _parse_iso_to_naive_utc(end_q)   if end_q   else None

    q = AgendaEvent.query.filter_by(user_id=u.id)
    if start_dt:
        q = q.filter(AgendaEvent.end >= start_dt)
    if end_dt:
        q = q.filter(AgendaEvent.start <= end_dt)

    events: list[dict[str, Any]] = []

    # Eventos da Agenda
    for e in q.all():
        events.append({
            "id": getattr(e, "id", None),
            "title": e.title or "Evento",
            "start": e.start.isoformat() if e.start else None,
            "end":   e.end.isoformat()   if e.end   else None,
            "allDay": False,
            "className": "holiday-event" if ((e.type or "").lower() == "bloqueio") else "patient-event",
            "extendedProps": {
                "notes": getattr(e, "notes", None),
                "type": getattr(e, "type", None),
                "billing": getattr(e, "billing", None),
                "insurer": getattr(e, "insurer", None),
            },
        })

    return jsonify(events)


# ------------------------------------------------------------------------------
# Agenda (API) – cria evento + agenda lembretes WhatsApp
# ------------------------------------------------------------------------------
@app.route('/api/add_event', methods=['POST'])
@login_required
def api_add_event():
    """
    Cria um AgendaEvent e agenda lembretes para médico e paciente.
    """
    u = current_user()
    data = request.get_json(silent=True) or {}

    title   = (data.get('title') or '').strip()
    phone   = (data.get('phone') or '').strip()
    start_s = (data.get('start') or '').strip()
    end_s   = (data.get('end') or '').strip() or None
    notes   = (data.get('notes') or '').strip()
    type_   = (data.get('type') or 'consulta').strip().lower()
    billing = (data.get('billing') or 'particular').strip().lower()
    insurer = (data.get('insurer') or '').strip()

    if not title or not start_s:
        return jsonify(success=False, error="Título e data/hora são obrigatórios."), 400

    start_dt = _parse_iso_to_naive_utc(start_s)
    if not start_dt:
        return jsonify(success=False, error="Formato de data/hora inválido (start)."), 400

    end_dt = _parse_iso_to_naive_utc(end_s) if end_s else start_dt + timedelta(hours=1)
    if end_s and not end_dt:
        return jsonify(success=False, error="Formato de data/hora inválido (end)."), 400

    ev = AgendaEvent(
        user_id=u.id,
        title=title,
        start=start_dt,
        end=end_dt,
        notes=notes or None,
        type=type_ or None,
        billing=billing or None,
        insurer=insurer or None,
    )
    db.session.add(ev)
    db.session.commit()

    # === WhatsApp lembretes ===
    from app import schedule_whatsapp_job  # garante o scheduler

    # Dados do lembrete
    patient_name = title
    clinic_name = u.username or "Clínica"
    date_str = start_dt.strftime("%d/%m/%Y")
    time_start = start_dt.strftime("%H:%M")
    time_end = end_dt.strftime("%H:%M") if end_dt else time_start

    # Médico: no mesmo dia
    if u.clinic_phone:
        schedule_whatsapp_job(
            func=send_reminder_doctor,
            run_at=start_dt.replace(hour=8, minute=0),
            kwargs={
                "doctor_phone": u.clinic_phone,
                "patient_name": patient_name,
                "clinic_name": clinic_name,
                "date_str": date_str,
                "time_start": time_start,
                "time_end": time_end
            }
        )

    # Paciente: um dia antes
    if phone:
        remind_time = (start_dt - timedelta(days=1)).replace(hour=8, minute=0)
        schedule_whatsapp_job(
            func=send_reminder_patient,
            run_at=remind_time,
            kwargs={
                "patient_phone": phone,
                "patient_name": patient_name,
                "clinic_name": clinic_name,
                "date_str": date_str,
                "time_start": time_start,
                "time_end": time_end
            }
        )

    return jsonify(success=True, event_id=ev.id), 201

scheduler = BackgroundScheduler()
scheduler.start()

def schedule_whatsapp_job(func, run_at, kwargs):
    """Agenda o envio de mensagens no horário correto."""
    scheduler.add_job(func, 'date', run_date=run_at, kwargs=kwargs)

@app.route('/api/events', methods=['POST'])
@login_required
def api_create_event_alias():
    return api_add_event()


@app.route('/api/events/<int:event_id>', methods=['PUT', 'DELETE'])
@login_required
def api_event_mutation(event_id: int):
    """
    PUT: atualiza o evento e reprograma lembretes quando a data muda.
    DELETE: remove o evento.
    """
    u = current_user()
    ev = AgendaEvent.query.get_or_404(event_id)
    if getattr(ev, 'user_id', None) != u.id:
        abort(403)

    if request.method == 'DELETE':
        db.session.delete(ev)
        db.session.commit()
        return jsonify(success=True)

    data = request.get_json(silent=True) or {}

    if 'start' in data:
        start_dt = _parse_iso_to_naive_utc((data.get('start') or '').strip())
        if not start_dt:
            return jsonify(success=False, error="Formato de data/hora inválido para 'start'."), 400
        ev.start = start_dt

        # Reagendar lembretes
        date_str = start_dt.strftime("%d/%m/%Y %H:%M")
        if u.clinic_phone:
            schedule_whatsapp_job(
                func=send_reminder_doctor,
                run_at=start_dt.replace(hour=9, minute=0),
                kwargs={"doctor_phone": u.clinic_phone, "date_time": date_str}
            )
        if ev.phone:
            schedule_whatsapp_job(
                func=send_reminder_patient,
                run_at=start_dt - timedelta(days=1),
                kwargs={"patient_phone": ev.phone, "date_time": date_str}
            )

    if 'end' in data:
        end_val = (data.get('end') or '').strip()
        if end_val:
            end_dt = _parse_iso_to_naive_utc(end_val)
            if not end_dt:
                return jsonify(success=False, error="Formato de data/hora inválido para 'end'."), 400
            ev.end = end_dt
        else:
            ev.end = None

    for key in ('title', 'notes', 'type', 'billing', 'insurer', 'phone'):
        if key in data:
            setattr(ev, key, ((data.get(key) or '').strip() or None))

    db.session.commit()
    return jsonify(success=True)

# ------------------------------------------------------------------------------
# Catálogo / Pacientes
# ------------------------------------------------------------------------------
@app.route('/catalog/register', methods=['GET', 'POST'])
@login_required
def register_patient():
    import time as _time

    u = current_user()

    # URL absoluta da imagem padrão (útil para gravar direto no campo profile_image)
    default_image_url = url_for('static', filename='images/user-icon.png')

    if request.method == 'POST':
        # -------- campos básicos
        name = (request.form.get('name') or '').strip()

        # -------- birthdate: aceita "13/09/2005", "2005-09-13" ou "13092005"
        birthdate_raw = (request.form.get('birthdate') or '').strip()
        birthdate = None
        if birthdate_raw:
            # normaliza 8 dígitos → dd/mm/aaaa
            only_digits = re.sub(r'\D', '', birthdate_raw)
            if len(only_digits) == 8:
                birthdate_try = f"{only_digits[:2]}/{only_digits[2:4]}/{only_digits[4:]}"
            else:
                birthdate_try = birthdate_raw

            for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
                try:
                    birthdate = datetime.strptime(birthdate_try, fmt).date()
                    break
                except Exception:
                    continue

        sex   = (request.form.get('sex') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        cpf   = (request.form.get('cpf') or request.form.get('document') or '').strip()
        cpf   = cpf.replace('.', '').replace('-', '')
        notes = (request.form.get('notes') or '').strip()

        phone_pri = (request.form.get('phone_primary') or request.form.get('phone') or '').strip()
        phone_sec = (request.form.get('phone_secondary') or '').strip()

        cep        = (request.form.get('cep') or request.form.get('zipcode') or '').strip()
        street     = (request.form.get('street') or '').strip()
        number     = (request.form.get('number') or '').strip()
        complement = (request.form.get('complement') or '').strip()
        district   = (request.form.get('district') or '').strip()
        city       = (request.form.get('city') or '').strip()
        state      = (request.form.get('state') or '').strip().upper()

        # vínculo médico (opcional)
        doctor_id = request.form.get('doctor_id')
        try:
            doctor_id = int(doctor_id) if doctor_id else None
        except Exception:
            doctor_id = None

        # -------- validação servidor (mantém o formulário preenchido se falhar)
        missing = []
        if not name: missing.append('name')
        if not birthdate: missing.append('birthdate')
        if not sex: missing.append('sex')
        if not phone_pri: missing.append('phone_primary')

        if missing:
            flash("Preencha todos os campos obrigatórios.", "warning")
            # Re-renderiza mantendo valores já digitados
            return render_template(
                'register_patient.html',
                form=request.form,
                errors=missing,
                default_image_url=default_image_url
            )

        if email and not basic_email(email):
            flash("E-mail inválido.", "warning")
            return render_template(
                'register_patient.html',
                form=request.form,
                errors=['email'],
                default_image_url=default_image_url
            )

        # -------- foto de perfil (opcional): salva em /static/uploads/patients
        profile_rel = default_image_url  # fallback padrão
        file = request.files.get('profile_image')
        if file and file.filename:
            if allowed_file(file.filename):
                filename = secure_filename(file.filename)
                ext = filename.rsplit('.', 1)[1].lower()

                dest_dir = os.path.join(STATIC_DIR, "uploads", "patients")
                os.makedirs(dest_dir, exist_ok=True)

                new_name = f"patient_{u.id}_{int(_time.time())}.{ext}"
                dest_path = os.path.join(dest_dir, new_name)
                file.save(dest_path)

                # salva caminho relativo /static/...
                profile_rel = "/" + os.path.relpath(dest_path, STATIC_DIR).replace("\\", "/")
            else:
                flash("Tipo de arquivo não permitido. Use png, jpg ou jpeg.", "warning")
                return render_template(
                    'register_patient.html',
                    form=request.form,
                    errors=['profile_image'],
                    default_image_url=default_image_url
                )

        # -------- cria paciente
        p = Patient(
            user_id=u.id,
            doctor_id=doctor_id,
            name=name,
            birthdate=birthdate,
            sex=sex or None,
            email=email or None,
            cpf=cpf or None,
            notes=notes or None,
            profile_image=profile_rel or default_image_url,
            phone_primary=phone_pri,
            phone_secondary=phone_sec or None,
            address_cep=cep or None,
            address_street=street or None,
            address_number=number or None,
            address_complement=complement or None,
            address_district=district or None,
            address_city=city or None,
            address_state=state or None,
        )
        db.session.add(p)
        db.session.commit()

        flash('Paciente cadastrado com sucesso.', 'success')
        return redirect(url_for('catalog'))

    # GET
    return render_template('register_patient.html', default_image_url=default_image_url)


@app.route('/catalog')
@login_required
def catalog():
    u = current_user()
    search = request.args.get('search', '').strip().lower()
    status = request.args.get('status', '').strip()

    patients = Patient.query.filter_by(user_id=u.id).all()
    if search:
        patients = [p for p in patients if search in (p.name or '').lower()]
    if status:
        patients = [p for p in patients if (p.status or '') == status]

    # Lista de médicos: se modelo tiver user_id, filtra; senão, lista todos
    base_docs = Doctor.query
    if hasattr(Doctor, 'user_id'):
        base_docs = base_docs.filter((Doctor.user_id == u.id) | (Doctor.user_id.is_(None)))
    doctors_list = base_docs.order_by(Doctor.name).all()

    return render_template('catalog.html', patients=patients, doctors=doctors_list)

# ------------------------------------------------------------------------------
# Editar Paciente (com upload de foto via SecureFile)
# ------------------------------------------------------------------------------
@app.route('/edit_patient/<int:patient_id>', methods=['GET', 'POST'])
@login_required
def edit_patient(patient_id):
    import time as _time

    u = current_user()
    patient = Patient.query.get_or_404(patient_id)
    if patient.user_id != u.id:
        abort(403)

    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()

        # -----------------------
        # Data de nascimento
        # -----------------------
        birthdate_s = (request.form.get('birthdate') or '').strip()

        # Se o usuário digitar apenas números (ex: 13092005),
        # formatamos automaticamente para 13/09/2005
        if birthdate_s and birthdate_s.isdigit() and len(birthdate_s) == 8:
            birthdate_s = f"{birthdate_s[:2]}/{birthdate_s[2:4]}/{birthdate_s[4:]}"

        birthdate = None
        if birthdate_s:
            for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
                try:
                    birthdate = datetime.strptime(birthdate_s, fmt).date()
                    break
                except Exception:
                    continue

        sex       = (request.form.get('sex') or (patient.sex or '')).strip()
        email     = (request.form.get('email') or '').strip().lower()
        cpf       = (request.form.get('cpf') or request.form.get('document') or '').strip().replace('.', '').replace('-', '')
        notes     = (request.form.get('notes') or '').strip()
        phone_pri = (request.form.get('phone_primary') or request.form.get('phone') or '').strip()
        phone_sec = (request.form.get('phone_secondary') or '').strip()
        cep       = (request.form.get('cep') or request.form.get('zipcode') or '').strip()
        street    = (request.form.get('street') or '').strip()
        number    = (request.form.get('number') or '').strip()
        complement= (request.form.get('complement') or '').strip()
        district  = (request.form.get('district') or '').strip()
        city      = (request.form.get('city') or '').strip()
        state     = (request.form.get('state') or '').strip().upper()

        # -----------------------
        # Validação mínima
        # -----------------------
        if not name:
            flash("Preencha o nome do paciente.", "warning")
            return redirect(url_for('edit_patient', patient_id=patient.id))

        # -----------------------
        # Upload de foto (opcional)
        # -----------------------
        file = request.files.get('profile_image')
        if file and file.filename:
            if not allowed_file(file.filename):
                flash("Tipo de arquivo não permitido. Use png, jpg ou jpeg.", "warning")
                return redirect(url_for('edit_patient', patient_id=patient.id))

            filename = secure_filename(file.filename)
            ext = filename.rsplit('.', 1)[1].lower()
            if ext not in {"png", "jpg", "jpeg"}:
                flash("Tipo de arquivo não permitido. Use png, jpg ou jpeg.", "warning")
                return redirect(url_for('edit_patient', patient_id=patient.id))

            content = file.read()
            if not content:
                flash("Arquivo de imagem inválido.", "warning")
                return redirect(url_for('edit_patient', patient_id=patient.id))

            # Remove imagem anterior
            old_rel = (patient.profile_image or "").replace("\\", "/")
            old_sid = _extract_securefile_id_from_url(old_rel)
            if old_sid:
                _delete_securefile_if_owned(old_sid, u.id)
            else:
                _safe_remove_patient_photo(old_rel)

            new_name = f"patient_{u.id}_{int(_time.time())}.{ext}"
            sf = SecureFile(
                user_id=u.id,
                kind="patient_profile_image",
                filename=new_name,
                mime_type=file.mimetype or f"image/{ext}",
                size_bytes=len(content),
                data=content,
            )
            db.session.add(sf)
            db.session.flush()
            patient.profile_image = f"/files/img/{sf.id}"

        # -----------------------
        # Atualiza dados no banco
        # -----------------------
        patient.name               = name
        patient.birthdate          = birthdate
        patient.sex                = sex or None
        patient.email              = email or None
        patient.cpf                = cpf or None
        patient.notes              = notes or None
        patient.phone_primary      = phone_pri
        patient.phone_secondary    = phone_sec or None
        patient.address_cep        = cep or None
        patient.address_street     = street or None
        patient.address_number     = number or None
        patient.address_complement = complement or None
        patient.address_district   = district or None
        patient.address_city       = city or None
        patient.address_state      = state or None

        db.session.commit()
        flash("Paciente atualizado com sucesso.", "success")
        return redirect(url_for('catalog'))

    return render_template('edit_patient.html', patient=patient)

# ------------------------------------------------------------------------------
# Foto do paciente (upload/remover) — compatível com SecureFile
# ------------------------------------------------------------------------------
def _patient_photos_dir():
    dest_dir = os.path.join(STATIC_DIR, "uploads", "patients")
    os.makedirs(dest_dir, exist_ok=True)
    return dest_dir

def _safe_remove_patient_photo(rel_path: str):
    try:
        if not rel_path:
            return
        abs_path = os.path.join(STATIC_DIR, rel_path.replace("\\", "/"))
        allowed_root = os.path.realpath(os.path.join(STATIC_DIR, "uploads", "patients"))
        abs_norm = os.path.realpath(abs_path)
        if abs_norm.startswith(allowed_root) and os.path.exists(abs_norm):
            os.remove(abs_norm)
    except Exception as e:
        print("[patient_photo] remove error:", e)


@app.route('/patients/<int:patient_id>/photo', methods=['POST'], endpoint='patient_update_photo')
@login_required
def patient_update_photo(patient_id: int):
    import time as _time

    u = current_user()
    p = Patient.query.get_or_404(patient_id)
    if p.user_id != u.id:
        abort(403)

    file = request.files.get("profile_image")
    if not file or not file.filename:
        flash("Selecione um arquivo de imagem.", "warning")
        return redirect(url_for('edit_patient', patient_id=p.id))

    if not allowed_file(file.filename):
        flash("Tipo de arquivo não permitido. Use png, jpg ou jpeg.", "warning")
        return redirect(url_for('edit_patient', patient_id=p.id))

    filename = secure_filename(file.filename)
    ext = filename.rsplit(".", 1)[1].lower()
    if ext not in {"png", "jpg", "jpeg"}:
        flash("Tipo de arquivo não permitido. Use png, jpg ou jpeg.", "warning")
        return redirect(url_for('edit_patient', patient_id=p.id))

    content = file.read()
    if not content:
        flash("Arquivo de imagem inválido.", "warning")
        return redirect(url_for('edit_patient', patient_id=p.id))

    # Remove imagem anterior
    old_rel = (p.profile_image or "").replace("\\", "/")
    old_sid = _extract_securefile_id_from_url(old_rel)
    if old_sid:
        _delete_securefile_if_owned(old_sid, u.id)
    else:
        _safe_remove_patient_photo(old_rel)

    new_name = f"patient_{u.id}_{int(_time.time())}.{ext}"
    sf = SecureFile(
        user_id=u.id,
        kind="patient_profile_image",
        filename=new_name,
        mime_type=file.mimetype or f"image/{ext}",
        size_bytes=len(content),
        data=content,
    )
    db.session.add(sf)
    db.session.flush()

    p.profile_image = f"/files/img/{sf.id}"
    db.session.commit()

    flash("Foto de perfil atualizada!", "success")
    return redirect(url_for('edit_patient', patient_id=p.id))


@app.route('/patients/<int:patient_id>/photo/delete', methods=['POST'], endpoint='patient_remove_photo')
@login_required
def patient_remove_photo(patient_id: int):
    """
    Remove a foto de perfil do paciente, seja do banco (SecureFile) ou do sistema de arquivos.
    Em seguida, volta para a imagem padrão.
    """
    u = current_user()
    p = Patient.query.get_or_404(patient_id)
    if p.user_id != u.id:
        abort(403)

    # remove imagem atual (do SecureFile ou física)
    old_rel = (p.profile_image or "").replace("\\", "/")
    old_sid = _extract_securefile_id_from_url(old_rel)
    if old_sid:
        _delete_securefile_if_owned(old_sid, u.id)
    else:
        _safe_remove_patient_photo(old_rel)

    # volta para a imagem padrão
    p.profile_image = url_for('static', filename='images/user-icon.png')
    db.session.commit()

    flash("Foto de perfil removida.", "info")
    return redirect(url_for('edit_patient', patient_id=p.id))


@app.route('/files/img/<int:file_id>')
@login_required
def serve_image(file_id: int):
    """
    Retorna imagem de perfil armazenada no banco (SecureFile).
    """
    u = current_user()
    sf = SecureFile.query.get_or_404(file_id)
    if sf.user_id is not None and sf.user_id != u.id:
        abort(403)
    if not (sf.mime_type or "").lower().startswith("image/"):
        abort(404)

    bio = BytesIO(sf.data)
    bio.seek(0)
    return send_file(
        bio,
        as_attachment=False,
        download_name=sf.filename or f"image_{file_id}",
        mimetype=sf.mime_type or "image/jpeg",
    )


@app.route('/patient_info/<int:patient_id>')
@login_required
def patient_info(patient_id):
    """
    Exibe informações do paciente.
    """
    u = current_user()
    patient = Patient.query.get_or_404(patient_id)
    if patient.user_id != u.id:
        abort(403)
    return render_template('patient_info.html', patient=patient)


@app.route('/api/add_patient', methods=['POST'])
@login_required
def api_add_patient():
    """
    Cria um paciente via JSON (ex.: importação de PDF).
    Sempre garante imagem padrão quando nenhuma é enviada.
    """
    u = current_user()
    data = request.get_json(silent=True) or {}

    name        = (data.get("name") or "").strip()
    birthdate_s = (data.get("birthdate") or "").strip()
    sex         = (data.get("sex") or data.get("gender") or "").strip()
    email       = (data.get("email") or "").strip().lower()
    cpf         = (data.get("cpf") or "").strip().replace('.', '').replace('-', '')
    notes       = (data.get("notes") or data.get("prescription") or "").strip()
    phone_pri   = (data.get("phone_primary") or data.get("phone") or "").strip()
    phone_sec   = (data.get("phone_secondary") or "").strip()
    cep         = (data.get("cep") or "").strip()
    street      = (data.get("street") or "").strip()
    number      = (data.get("number") or "").strip()
    complement  = (data.get("complement") or "").strip()
    district    = (data.get("district") or "").strip()
    city        = (data.get("city") or "").strip()
    state       = (data.get("state") or "").strip().upper()

    # vínculo com médico (opcional)
    doctor_id = data.get("doctor_id")
    try:
        doctor_id = int(doctor_id) if doctor_id else None
    except Exception:
        doctor_id = None

    if not (name and birthdate_s and sex and phone_pri):
        return jsonify(success=False, error='Campos obrigatórios: nome, data de nascimento, sexo, celular.'), 400

    # aceita dd/mm/aaaa e yyyy-mm-dd
    birthdate = None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            birthdate = datetime.strptime(birthdate_s, fmt).date()
            break
        except Exception:
            continue
    if not birthdate:
        return jsonify(success=False, error='Data de nascimento inválida'), 400

    if email and not basic_email(email):
        return jsonify(success=False, error='E-mail inválido'), 400

    # ✅ sempre cria com a imagem padrão se nenhuma for enviada
    p = Patient(
        user_id=u.id,
        doctor_id=doctor_id,
        name=name,
        birthdate=birthdate,
        sex=sex,
        email=email or None,
        cpf=cpf or None,
        notes=notes or None,
        profile_image=url_for('static', filename='images/user-icon.png'),
        phone_primary=phone_pri,
        phone_secondary=phone_sec or None,
        address_cep=cep or None,
        address_street=street or None,
        address_number=number or None,
        address_complement=complement or None,
        address_district=district or None,
        address_city=city or None,
        address_state=state or None,
    )
    db.session.add(p)
    db.session.commit()
    return jsonify(success=True, patient_id=p.id), 201


@app.route('/delete_patient/<int:patient_id>', methods=['POST'])
@login_required
def delete_patient(patient_id):
    """
    Exclui paciente e suas consultas.
    """
    u = current_user()
    p = Patient.query.get_or_404(patient_id)
    if p.user_id != u.id:
        abort(403)

    Consult.query.filter_by(patient_id=patient_id).delete(synchronize_session=False)
    db.session.delete(p)
    db.session.commit()
    flash('Paciente removido.', 'info')
    return redirect(url_for('catalog'))


@app.route('/toggle_patient_status/<int:patient_id>/<new_status>', methods=['GET', 'POST'])
@login_required
def toggle_patient_status(patient_id, new_status):
    """
    Altera o status (Ativo/Inativo) do paciente.
    """
    u = current_user()
    p = Patient.query.get_or_404(patient_id)
    if p.user_id != u.id:
        abort(403)

    p.status = new_status
    db.session.commit()
    return redirect(url_for('catalog'))


# ------------------------------------------------------------------------------
# Médicos
# ------------------------------------------------------------------------------

def _doctor_scoped_query():
    """
    Retorna somente médicos do usuário logado.
    Requer coluna doctors.user_id (migração acima já cria).
    """
    u = current_user()
    base = Doctor.query
    if hasattr(Doctor, 'user_id'):
        base = base.filter(Doctor.user_id == u.id)
    return base

def _doctor_get_or_404_scoped(doctor_id: int):
    d = Doctor.query.get_or_404(doctor_id)
    if hasattr(Doctor, 'user_id'):
        if d.user_id != current_user().id:
            abort(403)
    return d

def get_or_create_default_doctor() -> int:
    name = "(Sem médico)"
    try:
        doc = Doctor.query.filter(Doctor.name == name).first()
    except Exception:
        try:
            apply_minimal_migrations()
        except Exception:
            pass
        doc = Doctor.query.filter(Doctor.name == name).first()

    if not doc:
        doc = Doctor(name=name)
        db.session.add(doc)
        db.session.commit()
    return doc.id

@app.route('/doctors')
@login_required
def doctors():
    u = current_user()
    q = (request.args.get('q') or '').strip().lower()
    specialty_f = (request.args.get('specialty') or '').strip()

    base = _doctor_scoped_query()

    if q:
        like = f"%{q}%"
        base = base.filter(
            or_(
                Doctor.name.ilike(like),
                Doctor.crm.ilike(like),
                Doctor.specialty.ilike(like),
                Doctor.email.ilike(like)
            )
        )

    if specialty_f:
        base = base.filter(Doctor.specialty == specialty_f)

    items = base.order_by(Doctor.id.desc()).all()

    specs = [r[0] for r in db.session.query(Doctor.specialty)
             .filter(Doctor.specialty.isnot(None))
             .filter(Doctor.specialty != '')
             .distinct()
             .order_by(Doctor.specialty.asc())
             .all()]

    return render_template('doctors.html', doctors=items, specialties=specs, notifications_unread=0)

@app.route('/api_doctors')
def api_doctors():
    base = _doctor_scoped_query().order_by(Doctor.name)
    docs = base.all()
    return jsonify([{"id": d.id, "name": d.name} for d in docs])

@app.route('/doctors/add', methods=['POST'], endpoint='add_doctor_route')
@login_required
def add_doctor_route():
    u = current_user()
    name      = (request.form.get('name') or '').strip()
    crm       = (request.form.get('crm') or '').strip()
    email     = (request.form.get('email') or '').strip().lower()
    phone     = (request.form.get('phone') or '').strip()
    specialty = (request.form.get('specialty') or '').strip()

    if not name:
        flash('Informe o nome do profissional.', 'warning')
        return redirect(url_for('doctors'))

    if email and not basic_email(email):
        flash('E-mail inválido.', 'warning')
        return redirect(url_for('doctors'))

    # Se modelo tiver user_id, preenche com o usuário atual
    d_kwargs = dict(name=name or None, crm=crm or None, email=email or None,
                    phone=phone or None, specialty=specialty or None)
    if hasattr(Doctor, 'user_id'):
        d_kwargs['user_id'] = u.id

    d = Doctor(**d_kwargs)
    db.session.add(d)
    db.session.commit()
    flash('Profissional cadastrado com sucesso!', 'success')
    return redirect(url_for('doctors'))

@app.route('/doctors/<int:doctor_id>', methods=['GET', 'POST'], endpoint='doctor_view')
@login_required
def doctor_view(doctor_id):
    d = _doctor_get_or_404_scoped(doctor_id)  # << usa o helper correto

    if request.method == 'POST':
        d.name      = (request.form.get('name') or '').strip()
        d.email     = (request.form.get('email') or '').strip()
        d.crm       = (request.form.get('crm') or '').strip()
        d.phone     = (request.form.get('phone') or '').strip()
        d.specialty = (request.form.get('specialty') or '').strip()
        try:
            db.session.commit()
            flash('Profissional atualizado com sucesso.', 'success')
            return redirect(url_for('doctors'))
        except Exception as e:
            db.session.rollback()
            flash(f'Falha ao salvar: {e}', 'warning')

    return render_template('doctor_view.html', doctor=d)

@app.route('/doctors/<int:doctor_id>/update', methods=['POST'])
@login_required
def doctor_update(doctor_id):
    d = _doctor_get_or_404_scoped(doctor_id)

    d.name       = (request.form.get('name') or '').strip() or d.name
    d.email      = (request.form.get('email') or '').strip() or None
    d.crm        = (request.form.get('crm') or '').strip() or None
    d.phone      = (request.form.get('phone') or '').strip() or None
    d.specialty  = (request.form.get('specialty') or '').strip() or None

    db.session.commit()
    flash('Profissional atualizado!', 'success')
    return redirect(url_for('doctor_view', doctor_id=d.id))

@app.route('/doctor/<int:doctor_id>/edit', methods=['GET', 'POST'], endpoint='doctor_edit')
@login_required
def doctor_edit(doctor_id):
    d = _doctor_get_or_404_scoped(doctor_id)

    if request.method == 'POST':
        name      = (request.form.get('name') or '').strip()
        crm       = (request.form.get('crm') or '').strip()
        email     = (request.form.get('email') or '').strip().lower()
        phone     = (request.form.get('phone') or '').strip()
        specialty = (request.form.get('specialty') or '').strip()

        if not name:
            flash("Nome é obrigatório.", "warning")
            return redirect(url_for('doctor_edit', doctor_id=doctor_id))
        if email and not basic_email(email):
            flash("E-mail inválido.", "warning")
            return redirect(url_for('doctor_edit', doctor_id=doctor_id))

        d.name = name
        d.crm = crm or None
        d.email = email or None
        d.phone = phone or None
        d.specialty = specialty or None

        db.session.commit()
        flash("Profissional atualizado com sucesso!", "success")
        return redirect(url_for('doctors'))

    return render_template('doctor_edit.html', doctor=d)

@app.route('/doctor/<int:doctor_id>/delete', methods=['POST'], endpoint='doctor_delete')
@login_required
def doctor_delete(doctor_id):
    d = _doctor_get_or_404_scoped(doctor_id)
    db.session.delete(d)
    db.session.commit()
    flash("Profissional removido.", "info")
    return redirect(url_for('doctors'))

# ------------------------------------------------------------------------------
# Cotações / Fornecedores / Produtos
# ------------------------------------------------------------------------------
@app.route('/quotes', methods=['GET'], endpoint='quote_index')
@login_required
def quote_index():
    u = current_user()
    # busca todas as cotações do usuário
    quotes = Quote.query.filter(Quote.user_id == u.id).order_by(Quote.created_at.desc()).all()

    # Ajusta timezone e contagens
    for q in quotes:
        q.created_at_br = q.created_at.astimezone(ZoneInfo("America/Sao_Paulo")) if q.created_at else None
        # contagem de fornecedores via relationship
        q.suppliers_count = len(q.suppliers or [])
        # contagem de respostas via relationship
        q.responses_count = len(q.responses or [])

    return render_template('quote_index.html', quotes=quotes)


@app.route('/quotes/<int:quote_id>/results', methods=['GET'], endpoint='quote_results')
@login_required
def quote_results(quote_id: int):
    u = current_user()
    q = Quote.query.get_or_404(quote_id)
    if q.user_id != u.id:
        abort(403)

    # 1) Itens: converte o JSON salvo em items (continua Text mas é JSON válido)
    items: list[str] = []
    try:
        parsed = json.loads(q.items or "[]")
        if isinstance(parsed, list):
            items = [str(x).strip() for x in parsed if str(x).strip()]
    except Exception:
        # fallback: caso seja texto simples
        raw = (q.items or "").strip()
        items = [ln.strip() for ln in raw.splitlines() if ln.strip()]

    # 2) Fornecedores diretamente do relacionamento
    suppliers = q.suppliers or []
    supplier_names = [s.name or f"Fornecedor #{s.id}" for s in suppliers]
    quote_suppliers_ids = [s.id for s in suppliers]

    # 3) Respostas via relacionamento
    quote_responses: dict[int, dict] = {}
    for r in q.responses:
        sid = r.supplier_id
        if not sid:
            continue
        # respostas armazenadas como JSON em r.answers
        answers = []
        try:
            payload = json.loads(r.answers) if r.answers else []
            if isinstance(payload, list):
                answers = payload
            elif isinstance(payload, dict) and "answers" in payload:
                answers = payload.get("answers") or []
        except Exception:
            pass

        norm = []
        for a in answers:
            if isinstance(a, dict):
                price = str(a.get("price", "")).strip()
                deadline = a.get("deadline", "")
                try:
                    price_val = Decimal(str(price).replace(",", "."))
                    price = f"{price_val:.2f}".replace(".", ",")
                except Exception:
                    price = price or ""
                try:
                    deadline = int(deadline)
                except Exception:
                    deadline = str(deadline).strip() or ""
                norm.append({"price": price, "deadline": deadline})
        quote_responses[sid] = {"answers": norm}

    # 4) Melhor preço por item
    best_per_item: dict[int, int] = {}
    for idx in range(len(items)):
        best_sid = None
        best_price = None
        for sid in quote_suppliers_ids:
            resp = quote_responses.get(sid)
            if not resp:
                continue
            answers = resp.get("answers") or []
            if idx >= len(answers):
                continue
            a = answers[idx]
            price_s = str(a.get("price", "")).strip()
            try:
                price_val = Decimal(price_s.replace(".", "").replace(",", ".")) if price_s else None
            except Exception:
                price_val = None
            if price_val is not None and (best_price is None or price_val < best_price):
                best_price = price_val
                best_sid = sid
        if best_sid is not None:
            best_per_item[idx] = best_sid

    return render_template(
        'quote_results.html',
        quote=q,
        supplier_names=supplier_names,
        quote_items=list(enumerate(items)),
        quote_suppliers=quote_suppliers_ids,
        quote_responses=quote_responses,
        best_per_item=best_per_item,
        notifications_unread=0
    )


@app.route('/quotes/create', methods=['GET', 'POST'], endpoint='create_quote')
@login_required
def create_quote():
    u = current_user()
    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        raw_items = (request.form.get('items') or '').strip()
        items_list = [ln.strip() for ln in raw_items.splitlines() if ln.strip()]

        # busca instâncias Supplier
        supplier_ids = [int(x) for x in request.form.getlist('suppliers') if x.strip()]
        selected_suppliers = Supplier.query.filter(
            Supplier.user_id == u.id,
            Supplier.id.in_(supplier_ids)
        ).all() if supplier_ids else []

        q = Quote(
            user_id=u.id,
            title=title,
            items=json.dumps(items_list, ensure_ascii=False)
        )
        q.suppliers = selected_suppliers  # type: ignore

        db.session.add(q)
        db.session.commit()

        # === ✅ WhatsApp sending with signed public link ===
        try:
            from itsdangerous import URLSafeSerializer
            s = URLSafeSerializer(current_app.config['SECRET_KEY'])
            token = s.dumps(q.id)

            # Link that suppliers will click to view the quote publicly
            public_link = url_for('quote_view', quote_id=q.id, _external=True)

            # send WhatsApp message to every selected supplier
            for s_item in selected_suppliers:
                if s_item.phone:
                    wa_err = send_quote_whatsapp(
                        supplier_name=s_item.name,
                        quote_title=title,
                        phone=s_item.phone,
                        quote_items=items_list,
                        response_url=public_link
                    )
                    if wa_err:
                        current_app.logger.error(
                            f"[WA] send_quote_whatsapp failed for supplier {s_item.name}: {wa_err}"
                        )
        except Exception as e:
            current_app.logger.error(f"[WA] erro no pipeline de envio da cotação: {e}")

        flash('Cotação criada com sucesso!', 'success')
        return redirect(url_for('quote_index'))

    suppliers = Supplier.query.filter_by(user_id=u.id).all()
    return render_template('create_quote.html', suppliers=suppliers)


@app.route('/quotes/<int:quote_id>', methods=['GET'], endpoint='quote_view')
@login_required
def quotes_view(quote_id):
    u = current_user()
    q = Quote.query.get_or_404(quote_id)
    if q.user_id != u.id:
        abort(403)
    return render_template('quote_view.html', quote=q)


@app.route('/quotes/<int:quote_id>/delete', methods=['POST'], endpoint='quote_delete')
@login_required
def quotes_delete(quote_id):
    u = current_user()
    q = Quote.query.get_or_404(quote_id)
    if q.user_id != u.id:
        abort(403)
    db.session.delete(q)
    db.session.commit()
    flash('Cotação removida.', 'info')
    return redirect(url_for('quote_index'))

@app.route('/suppliers/add', methods=['POST'], endpoint='add_supplier')
@login_required
def add_supplier():
    u = current_user()
    name  = (request.form.get('name') or '').strip()
    phone = (request.form.get('phone') or '').strip()
    email = (request.form.get('email') or '').strip()

    if not name:
        flash("Nome é obrigatório.", "warning")
        return redirect(url_for('suppliers'))

    s = Supplier(user_id=u.id, name=name, phone=phone or None, email=email or None)
    db.session.add(s)
    db.session.commit()

    flash("Fornecedor cadastrado com sucesso!", "success")
    return redirect(url_for('suppliers'))

@app.route('/suppliers')
@login_required
def suppliers():
    u = current_user()
    sups = Supplier.query.filter_by(user_id=u.id).order_by(Supplier.name.asc()).all()
    try:
        return render_template('suppliers.html', suppliers=sups)
    except TemplateNotFound:
        lis = "".join(f"<li>{s.name} — {s.email or ''} {s.phone or ''}</li>" for s in sups)
        return f"<h1>Fornecedores</h1><ul>{lis or '<li>(vazio)</li>'}</ul>"
    
@app.route('/api/suppliers', methods=['GET', 'POST'])
@login_required
def api_suppliers():
    u = current_user()

    if request.method == 'GET':
        sups = Supplier.query.filter_by(user_id=u.id).order_by(Supplier.name.asc()).all()
        return jsonify([{
            "id": s.id,
            "name": s.name,
            "phone": s.phone,
            "email": s.email
        } for s in sups])

    # POST (criar)
    data = request.get_json(silent=True) or {}
    name  = (data.get('name')  or '').strip()
    phone = (data.get('phone') or '').strip()
    email = (data.get('email') or '').strip()
    if not name:
        return jsonify(success=False, error="Nome é obrigatório."), 400

    s = Supplier(user_id=u.id, name=name, phone=phone or None, email=email or None)
    db.session.add(s)
    db.session.commit()
    return jsonify(success=True, id=s.id, name=s.name)

@app.route('/products', methods=['GET'])
@login_required
def products():
    u = current_user()

    q = Product.query.filter(Product.user_id == u.id)

    # pesquisa por nome/código (exemplo)
    search = (request.args.get('search') or '').strip()
    if search:
        like = f"%{search}%"
        q = q.filter(
            or_(
                func.lower(Product.name).like(func.lower(like)),
                func.lower(func.coalesce(Product.code, '')).like(func.lower(like))
            )
        )

    # filtro de status com trim para evitar espaços
    status = (request.args.get('status') or '').strip()
    if status in ('Ativo', 'Inativo'):
        q = q.filter(func.trim(Product.status) == status)

    q = q.order_by(Product.created_at.desc())

    products = q.all()
    return render_template('products.html', products=products)

def _to_decimal(val, default="0"):
    if val is None:
        return Decimal(default)
    s = str(val).strip().replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return Decimal(default)

def _to_int(val, default=0):
    try:
        return int(str(val).strip())
    except Exception:
        return default

@app.route('/stock_edit/<int:product_id>', methods=['POST'])
@login_required
def stock_edit(product_id):
    u = current_user()
    p = Product.query.get_or_404(product_id)
    if p.user_id != u.id:
        abort(403)

    code           = (request.form.get('code') or '').strip()
    name           = (request.form.get('name') or '').strip()
    quantity       = _to_int(request.form.get('quantity'), p.quantity or 0)
    purchase_price = float(_to_decimal(request.form.get('purchase_price'), str(p.purchase_price or 0)))
    sale_price     = float(_to_decimal(request.form.get('sale_price'), str(p.sale_price or 0)))

    if not name:
        flash('Informe o nome do produto.', 'warning')
        return redirect(url_for('products'))

    try:
        p.code = code or None
        p.name = name
        p.quantity = max(quantity, 0)
        p.purchase_price = purchase_price
        p.sale_price = sale_price
        db.session.commit()
        flash('Produto atualizado com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Falha ao atualizar produto: {e}', 'warning')

    return redirect(url_for('products'))

@app.route('/api/stock_movement', methods=['POST'])
@login_required
def api_stock_movement():
    u = current_user()
    data = request.get_json(silent=True) or {}

    product_id = _to_int(data.get('product_id'), 0)
    qty        = _to_int(data.get('quantity'), 0)
    notes      = (data.get('notes') or '').strip()
    type_      = (data.get('type') or '').strip().lower()

    if not product_id or not qty:
        return jsonify(success=False, error='Dados inválidos.'), 400

    p = Product.query.get_or_404(product_id)
    if p.user_id != u.id:
        abort(403)

    if type_ == 'out':
        qty = -abs(qty)
    elif type_ == 'in':
        qty = abs(qty)

    new_qty = (p.quantity or 0) + qty
    if new_qty < 0:
        return jsonify(success=False, error='Estoque insuficiente para saída.'), 400

    try:
        # Atualiza a quantidade
        p.quantity = new_qty

        # ✅ Registra movimentação
        movement = StockMovement(
            user_id=u.id,
            product_id=p.id,
            quantity=qty,
            type=type_,
            notes=notes,
            created_at=datetime.utcnow()
        )
        db.session.add(movement)
        db.session.commit()

        return jsonify(success=True, product_id=p.id, quantity=p.quantity)
    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, error=f'Falha ao registrar movimentação: {e}'), 500


@app.route('/stock_movement', methods=['POST'])
@login_required
def stock_movement():
    u = current_user()

    if request.is_json:
        data = request.get_json(silent=True) or {}
        product_id = _to_int(data.get('product_id'), 0)
        qty        = _to_int(data.get('quantity'), 0)
        notes      = (data.get('notes') or '').strip()
        type_      = (data.get('type') or '').strip().lower()
    else:
        product_id = _to_int(request.form.get('product_id'), 0)
        qty        = _to_int(request.form.get('quantity'), 0)
        notes      = (request.form.get('notes') or '').strip()
        type_      = (request.form.get('type') or '').strip().lower()

    if not product_id or not qty:
        flash('Dados inválidos para movimentação.', 'warning')
        return redirect(url_for('products'))

    p = Product.query.get_or_404(product_id)
    if p.user_id != u.id:
        abort(403)

    if type_ == 'out':
        qty = -abs(qty)
    elif type_ == 'in':
        qty = abs(qty)

    new_qty = (p.quantity or 0) + qty
    if new_qty < 0:
        flash('Estoque insuficiente para saída.', 'warning')
        return redirect(url_for('products'))

    try:
        # Atualiza a quantidade
        p.quantity = new_qty

        # ✅ Registra movimentação
        movement = StockMovement(
            user_id=u.id,
            product_id=p.id,
            quantity=qty,
            type=type_,
            notes=notes,
            created_at=datetime.utcnow()
        )
        db.session.add(movement)
        db.session.commit()

        flash('Movimentação registrada!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Falha ao registrar movimentação: {e}', 'warning')

    return redirect(url_for('products'))


# ✅ NOVA ROTA - Histórico de movimentações (últimos 30 dias)
@app.route('/api/stock_history')
@login_required
def api_stock_history():
    u = current_user()
    limit_date = datetime.utcnow() - timedelta(days=30)

    movements = (
        db.session.query(StockMovement, Product.name)
        .join(Product, Product.id == StockMovement.product_id)
        .filter(StockMovement.user_id == u.id)
        .filter(StockMovement.created_at >= limit_date)
        .order_by(StockMovement.created_at.desc())
        .all()
    )

    records = []
    for m, product_name in movements:
        records.append({
            "date": m.created_at.strftime("%d/%m/%Y %H:%M"),
            "product": product_name,
            "type": "Entrada" if m.type == "in" else "Saída",
            "quantity": abs(m.quantity),
            "notes": m.notes
        })

    return jsonify(success=True, records=records)

@app.route('/products/add', methods=['POST'])
@login_required
def add_product_route():
    u = current_user()

    name           = (request.form.get('name') or '').strip()
    quantity       = _to_int(request.form.get('quantity'), 0)
    purchase_price = float(_to_decimal(request.form.get('purchase_price')))
    sale_price     = float(_to_decimal(request.form.get('sale_price')))

    if not name:
        flash('Informe o nome do produto.', 'warning')
        return redirect(url_for('products'))

    try:
        p = Product(
            user_id=u.id,
            name=name,
            purchase_price=purchase_price,
            sale_price=sale_price,
            quantity=quantity,
            status='Ativo',
            created_at=datetime.utcnow()
        )
        db.session.add(p)
        db.session.commit()
        flash('Produto cadastrado com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Falha ao salvar produto: {e}', 'warning')

    return redirect(url_for('products'))

@app.route('/delete_product/<int:product_id>', methods=['POST'])
@login_required
def delete_product(product_id):
    u = current_user()
    p = Product.query.get_or_404(product_id)
    if p.user_id != u.id:
        abort(403)
    try:
        db.session.delete(p)
        db.session.commit()
        flash('Produto removido.', 'info')
    except Exception as e:
        db.session.rollback()
        flash(f'Falha ao remover: {e}', 'warning')
    return redirect(url_for('products'))

@app.route('/products/<int:product_id>/toggle-status', methods=['POST'], endpoint='toggle_product_status')
@login_required
def toggle_product_status(product_id):
    u = current_user()
    p = Product.query.get_or_404(product_id)
    if p.user_id != u.id:
        abort(403)

    # Captura "next" para preservar filtros/pesquisa
    next_url = (
        request.form.get('next') or
        (request.get_json(silent=True) or {}).get('next') or
        request.referrer or
        url_for('products')
    )

    payload = request.get_json(silent=True) or {}
    new_status = request.form.get('new_status') or payload.get('new_status')
    if isinstance(new_status, str):
        new_status = new_status.strip()

    if new_status not in ('Ativo', 'Inativo', None):
        flash('Status inválido.', 'warning')
        return redirect(next_url)

    if not new_status:
        atual = (p.status or '').strip()
        new_status = 'Inativo' if atual == 'Ativo' else 'Ativo'

    p.status = new_status
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash(f'Falha ao alterar status: {e}', 'warning')
        return redirect(next_url)

    if request.is_json:
        return {'success': True, 'status': p.status}

    flash(f'Status atualizado para {p.status}.', 'success')
    return redirect(next_url)


# ♻️ LEGACY mantém o filtro via referrer/next também
@app.route('/toggle_product_status/<int:product_id>/<new_status>', methods=['GET'], endpoint='toggle_product_status_legacy')
@login_required
def toggle_product_status_legacy(product_id, new_status):
    u = current_user()
    p = Product.query.get_or_404(product_id)
    if p.user_id != u.id:
        abort(403)

    next_url = request.args.get('next') or request.referrer or url_for('products')

    if new_status not in ('Ativo', 'Inativo'):
        flash('Status inválido.', 'warning')
        return redirect(next_url)

    p.status = new_status.strip()
    try:
        db.session.commit()
        flash(f'Status atualizado para {p.status}.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Falha ao alterar status: {e}', 'warning')

    return redirect(next_url)

# --- SUPPLIERS: atualizar e deletar -----------------------------
@app.route('/update_supplier/<int:supplier_id>', methods=['POST'], endpoint='update_supplier')
@login_required
def update_supplier(supplier_id):
    u = current_user()
    s = Supplier.query.get_or_404(supplier_id)
    if getattr(s, 'user_id', None) and s.user_id != u.id:
        abort(403)

    name  = (request.form.get('name') or '').strip()
    phone = (request.form.get('phone') or '').strip()
    email = (request.form.get('email') or '').strip()

    if not name:
        flash('Nome é obrigatório.', 'warning')
        return redirect(url_for('suppliers'))

    s.name  = name
    s.phone = phone or None
    s.email = email or None
    db.session.commit()
    flash('Fornecedor atualizado com sucesso!', 'success')
    return redirect(url_for('suppliers'))

@app.route('/suppliers/<int:supplier_id>/delete', methods=['POST'], endpoint='delete_supplier')
@login_required
def delete_supplier(supplier_id):
    u = current_user()
    s = Supplier.query.get_or_404(supplier_id)
    if getattr(s, 'user_id', None) and s.user_id != u.id:
        abort(403)

    db.session.delete(s)
    db.session.commit()
    flash('Fornecedor excluído.', 'info')
    return redirect(url_for('suppliers'))

# ------------------------------------------------------------------------------
# Lista de Espera (Waitlist)
# ------------------------------------------------------------------------------
@app.route('/api/waitlist', methods=['GET', 'POST'])
@login_required
def api_waitlist():
    u = current_user()

    if request.method == 'GET':
        items = (
            WaitlistItem.query
            .filter_by(user_id=u.id)
            .order_by(WaitlistItem.created_at.desc())
            .all()
        )
        return jsonify({
            'items': [{
                'id': it.id,
                'name': it.name,
                'billing': it.billing,
                'email': it.email,
                'phone1': it.phone1,
                'phone2': it.phone2,
                'notes': it.notes,
                'created_at': it.created_at.isoformat()
            } for it in items]
        })

    # POST (criar)
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'error': 'Nome é obrigatório.'}), 400

    it = WaitlistItem(
        user_id=u.id,
        name=name,
        billing=(data.get('billing') or 'Particular').strip(),
        email=(data.get('email') or '').strip(),
        phone1=(data.get('phone1') or '').strip(),
        phone2=(data.get('phone2') or '').strip(),
        notes=(data.get('notes') or '').strip(),
    )
    db.session.add(it)
    db.session.commit()
    return jsonify({'success': True, 'id': it.id}), 201


@app.route('/api/waitlist/<int:item_id>', methods=['DELETE'])
@login_required
def api_waitlist_delete(item_id: int):
    u = current_user()
    it = WaitlistItem.query.get_or_404(item_id)
    if it.user_id != u.id:
        return jsonify({'success': False, 'error': 'Item não encontrado.'}), 404

    db.session.delete(it)
    db.session.commit()
    return jsonify({'success': True})

# ------------------------------------------------------------------------------
# Whatsapp API
# ------------------------------------------------------------------------------
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "").strip()
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()

def normalize_phone(phone: str) -> str:
    """Mantém só dígitos. Se for BR sem +55, tenta prefixar 55."""
    digits = re.sub(r"\D+", "", phone or "")
    if not digits:
        return digits
    # Se já vier com 55 no começo, mantém
    if digits.startswith("55"):
        return digits
    # Heurística simples: se parece com número nacional (10-11 dígitos), prefixa 55
    if len(digits) in (10, 11):
        return "55" + digits
    return digits

def whatsapp_upload_media(pdf_bytes: bytes, filename: str) -> Optional[str]:
    """Sobe o PDF para o WhatsApp e retorna media_id."""
    if not (WHATSAPP_TOKEN and WHATSAPP_PHONE_NUMBER_ID):
        print("[WA] Faltando WHATSAPP_TOKEN ou WHATSAPP_PHONE_NUMBER_ID.")
        return None
    url = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_NUMBER_ID}/media"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    files = {
        "file": (filename, pdf_bytes, "application/pdf")
    }
    data = {"messaging_product": "whatsapp"}
    try:
        r = requests.post(url, headers=headers, files=files, data=data, timeout=60)
        js = r.json() if r.content else {}
        if r.status_code in (200, 201) and js.get("id"):
            return js["id"]
        print("[WA upload] status:", r.status_code, "body:", r.text)
    except Exception as e:
        print("[WA upload] erro:", e)
    return None

def whatsapp_send_document(phone_number: str, media_id: str, filename: str) -> bool:
    """Envia o documento já upado (media_id) para o número."""
    if not (WHATSAPP_TOKEN and WHATSAPP_PHONE_NUMBER_ID):
        print("[WA] Faltando configurações.")
        return False
    url = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": normalize_phone(phone_number),
        "type": "document",
        "document": {"id": media_id, "filename": filename}
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=60)
        if r.status_code in (200, 201):
            return True
        print("[WA send] status:", r.status_code, "body:", r.text)
    except Exception as e:
        print("[WA send] erro:", e)
    return False

def try_send_whatsapp_pdf(phone_number: str, pdf_bytes: bytes, filename: str):
    """Pipeline completo: sobe o PDF e envia a mensagem. Silencioso em caso de falha."""
    phone = (phone_number or "").strip()
    if not phone:
        return
    media_id = whatsapp_upload_media(pdf_bytes, filename)
    if media_id:
        ok = whatsapp_send_document(phone, media_id, filename)
        print("[WA] enviado para", phone, "=>", ok)
    else:
        print("[WA] não foi possível obter media_id.")

# --- NOVO: helper para gerar o PDF em memória (reuso do /download_pdf) ---
def generate_result_pdf_bytes(*, patient: Patient, diagnostic_text: str, prescription_text: str, doctor_display_name: str) -> bytes:
    """
    Gera o PDF (mesma aparência do /download_pdf) e retorna os bytes.
    Também salva uma cópia no banco (PdfFile/SecureFile) para histórico.
    """
    from weasyprint import HTML
    from flask import current_app
    u = current_user()

    # --- Calcula idade ---
    def _calc_age(birthdate):
        try:
            today = datetime.today().date()
            return today.year - birthdate.year - ((today.month, today.day) < (birthdate.month, birthdate.day))
        except Exception:
            return None

    age_str = ""
    if getattr(patient, "birthdate", None):
        age_val = _calc_age(patient.birthdate)
        if age_val is not None:
            age_str = f"{age_val} anos"

    # --- Informações básicas ---
    sex_str = (patient.sex or "").strip()
    cpf_str = (patient.cpf or "").strip()
    phones = [x for x in [(patient.phone_primary or "").strip(), (patient.phone_secondary or "").strip()] if x]
    phone_str = " / ".join(phones)

    patient_lines = [
        f"Nome: {patient.name or '—'}",
        f"Data de nascimento: {patient.birthdate.strftime('%d/%m/%Y') if patient.birthdate else '—'}",
    ]
    if age_str: patient_lines.append(f"Idade: {age_str}")
    if sex_str: patient_lines.append(f"Sexo: {sex_str}")
    if cpf_str: patient_lines.append(f"CPF: {cpf_str}")
    if phone_str: patient_lines.append(f"Telefone: {phone_str}")
    patient_info = "\n".join(patient_lines)

    # --- Gera HTML com o template padrão ---
    html_str = render_template(
        "result_pdf.html",
        patient_info=patient_info,
        diagnostic_text=(diagnostic_text or "—"),
        prescription_text=(prescription_text or "—"),
        doctor_name=doctor_display_name or (getattr(u, "name", None) or u.username),
    )

    pdf_io = BytesIO()

    # --- 1) Geração via WeasyPrint ---
    try:
        HTML(string=html_str, base_url=current_app.root_path).write_pdf(pdf_io)
        pdf_io.seek(0)
    except Exception as e:
        print("[PDF/gen] WeasyPrint error, fallback ReportLab:", e)
        # --- 2) Fallback ReportLab ---
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import mm
        from reportlab.lib.utils import ImageReader

        c = canvas.Canvas(pdf_io, pagesize=A4)
        width, height = A4

        png_path = os.path.join(STATIC_DIR, "images", "logo.png")
        if os.path.exists(png_path):
            try:
                img = ImageReader(png_path)
                target_w = 40 * mm
                iw, ih = img.getSize()
                ratio = target_w / iw
                target_h = ih * ratio
                c.drawImage(img, width - target_w - 15 * mm, height - target_h - 15 * mm,
                            width=target_w, height=target_h, preserveAspectRatio=True, mask='auto')
            except Exception:
                pass

        c.setFont("Times-Bold", 16)
        c.drawCentredString(width / 2, height - 20 * mm, "Resultado da Análise - Ponza Health")

        c.setFont("Times-Roman", 11)
        y = height - 35 * mm
        for ln in patient_info.splitlines():
            c.drawString(20 * mm, y, ln)
            y -= 6 * mm

        y -= 4 * mm
        c.setFont("Times-Bold", 12)
        c.drawString(20 * mm, y, "Diagnóstico:")
        y -= 7 * mm
        c.setFont("Times-Roman", 11)
        for ln in (diagnostic_text or "—").splitlines():
            c.drawString(22 * mm, y, ln)
            y -= 6 * mm
            if y < 25 * mm:
                c.showPage()
                y = height - 20 * mm

        y -= 4 * mm
        c.setFont("Times-Bold", 12)
        c.drawString(20 * mm, y, "Prescrição:")
        y -= 7 * mm
        c.setFont("Times-Roman", 11)
        for ln in (prescription_text or "—").splitlines():
            c.drawString(22 * mm, y, ln)
            y -= 6 * mm
            if y < 40 * mm:
                c.showPage()
                y = height - 20 * mm

        c.setFont("Times-Roman", 11)
        c.line(60 * mm, 25 * mm, 150 * mm, 25 * mm)
        c.drawCentredString(105 * mm, 20 * mm, doctor_display_name or (getattr(u, "name", None) or u.username))
        c.showPage()
        c.save()
        pdf_io.seek(0)

    # --- Salva cópia no banco ---
    try:
        pdf_bytes = pdf_io.getvalue()
        consult = Consult.query.filter_by(patient_id=patient.id).order_by(Consult.date.desc()).first()
        consult_id = consult.id if consult else None
        display_name = f"Resultado_{(patient.name or 'Paciente').replace(' ', '_')}.pdf"

        _save_pdf_bytes_to_db(
            user_id=u.id,
            patient_id=patient.id,
            consult_id=consult_id,
            original_name=display_name,
            data=pdf_bytes,
            kind="result_pdf",
        )
    except Exception as e:
        db.session.rollback()
        print("[PDF/gen] erro ao salvar cópia do PDF no DB:", e)

    return pdf_io.getvalue()

# ------------------------------------------------------------------------------
# Erros / Contexto
# ------------------------------------------------------------------------------
@app.context_processor
def inject_globals():
    return {"now": datetime.utcnow()}

@app.errorhandler(403)
def forbidden(e):
    try:
        return render_template("403.html"), 403
    except TemplateNotFound:
        return "403 - Proibido", 403

@app.errorhandler(404)
def not_found(e):
    try:
        return render_template("404.html"), 404
    except TemplateNotFound:
        return "404 - Não encontrado", 404

@app.errorhandler(500)
def server_error(e):
    try:
        return render_template("500.html"), 500
    except TemplateNotFound:
        return "500 - Erro interno", 500

# ------------------------------------------------------------------------------
# Entrypoint
# ------------------------------------------------------------------------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv("PORT", "5000")), debug=True)

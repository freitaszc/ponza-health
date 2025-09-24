import os
import re
import secrets
from flask_migrate import Migrate
from models import db
from io import BytesIO
from mercado_pago import generate_subscription_link
from functools import wraps
from typing import Any, Optional, Callable, cast
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from uuid import uuid4
import json
import tempfile
import requests
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from flask_mail import Mail, Message

from dotenv import load_dotenv
from flask import (
    Flask, render_template, render_template_string, request, redirect, url_for,
    session, flash, jsonify, abort, send_file, g, current_app
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import select, text, func, or_
from werkzeug.middleware.proxy_fix import ProxyFix
from jinja2 import TemplateNotFound

from models import (
    db, User, Patient, Doctor, Consult, PackageUsage,
    Supplier, Product, AgendaEvent, Quote,
    SecureFile, PdfFile, WaitlistItem, ScheduledEmail,
)

# ------------------------------------------------------------------------------
# Inicialização / Config
# ------------------------------------------------------------------------------
load_dotenv()
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

migrate = Migrate(app, db)

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
# Database (Render Postgres, fallback SQLite)
# ------------------------------------------------------------------------------
def normalize_db_url(url: str) -> str:
    if not url:
        return url
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://") and "+psycopg2" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    if "sslmode=" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url

RAW_DATABASE_URL = (os.getenv('DATABASE_URL') or "").strip()
if RAW_DATABASE_URL:
    DATABASE_URL = normalize_db_url(RAW_DATABASE_URL)
else:
    db_path = os.path.join(BASE_DIR, 'web.db')
    DATABASE_URL = f"sqlite:///{db_path}"

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

from sqlalchemy import inspect, text

db.init_app(app)

with app.app_context():
    try:
        # Cria todas as tabelas conhecidas pelos modelos
        db.create_all()

        # ➜ criação segura da tabela de associação quote_suppliers
        insp = inspect(db.engine)
        if not insp.has_table("quote_suppliers"):
            # Nova forma: abrir uma conexão explícita e usar text()
            with db.engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE quote_suppliers (
                        quote_id INTEGER NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
                        supplier_id INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
                        PRIMARY KEY (quote_id, supplier_id)
                    )
                """))
                conn.commit()  # importante em SQLAlchemy 2.x
            print("[MIGRATION] Tabela quote_suppliers criada com sucesso.")
        else:
            print("[DB] Tabela quote_suppliers já existe.")

    except Exception as e:
        print("[DB] create_all error:", e)
        try:
            # Fallback: garantir modo WAL e recriar tabelas
            with db.engine.connect() as conn:
                conn.execute(text("PRAGMA journal_mode=WAL"))
                conn.commit()
            db.create_all()
        except Exception as e2:
            print("[DB] create_all fallback error:", e2)

# ------------------------------------------------------------------------------
# Migration
# ------------------------------------------------------------------------------
def apply_minimal_migrations():
    """
    Adiciona colunas/campos novos usados no app, caso ainda não existam.
    Não remove/renomeia; evita erros de 'no such column' em bases antigas.
    """
    with app.app_context():
        engine = db.engine
        dialect = engine.dialect.name  # 'sqlite' ou 'postgresql'

        def get_existing_columns(table: str):
            if dialect == "sqlite":
                q = text(f'PRAGMA table_info("{table}")')
                with engine.connect() as c:
                    rows = c.execute(q).fetchall()
                return {r[1] for r in rows}
            else:
                q = text("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = :tname
                """)
                with engine.connect() as c:
                    rows = c.execute(q, {"tname": table}).fetchall()
                return {r[0] for r in rows}

        def add_column_if_missing(table: str, coldef: str, colname: str):
            if colname not in get_existing_columns(table):
                try:
                    with engine.connect() as c:
                        c.execute(text(f'ALTER TABLE {table} ADD COLUMN {coldef}'))
                    print(f"[MIGRATION] {table}.{colname} criado.")
                except Exception as e:
                    print(f"[MIGRATION] Falha ao criar {table}.{colname}: {e}")

        # USERS
        add_column_if_missing("users", "company_id INTEGER", "company_id")
        add_column_if_missing("users", "plan VARCHAR(20)", "plan")
        add_column_if_missing("users", "plan_status VARCHAR(20)", "plan_status")
        add_column_if_missing("users", "plan_expires_at DATETIME", "plan_expires_at")
        add_column_if_missing("users", "trial_until DATETIME", "trial_until")
        add_column_if_missing("users", "profile_image VARCHAR(200)", "profile_image")
        add_column_if_missing("users", "birthdate DATE", "birthdate")
        add_column_if_missing("users", "name VARCHAR(120)", "name")

        # QUOTES
        add_column_if_missing("quotes", "user_id INTEGER", "user_id")

        # PATIENTS
        add_column_if_missing("patients", "owner_user_id INTEGER", "owner_user_id")
        add_column_if_missing("patients", "birthdate DATE", "birthdate")
        add_column_if_missing("patients", "sex VARCHAR(20)", "sex")
        add_column_if_missing("patients", "email VARCHAR(120)", "email")
        add_column_if_missing("patients", "notes TEXT", "notes")
        add_column_if_missing("patients", "phone_primary VARCHAR(20)", "phone_primary")
        add_column_if_missing("patients", "phone_secondary VARCHAR(20)", "phone_secondary")
        add_column_if_missing("patients", "address_cep VARCHAR(12)", "address_cep")
        add_column_if_missing("patients", "address_street VARCHAR(200)", "address_street")
        add_column_if_missing("patients", "address_number VARCHAR(20)", "address_number")
        add_column_if_missing("patients", "address_complement VARCHAR(100)", "address_complement")
        add_column_if_missing("patients", "address_district VARCHAR(120)", "address_district")
        add_column_if_missing("patients", "address_city VARCHAR(120)", "address_city")
        add_column_if_missing("patients", "address_state VARCHAR(2)", "address_state")
        add_column_if_missing("patients", "profile_image VARCHAR(200)", "profile_image")

        # AGENDA_EVENTS
        add_column_if_missing("agenda_events", "notes TEXT", "notes")
        add_column_if_missing("agenda_events", "type VARCHAR(20)", "type")
        add_column_if_missing("agenda_events", "billing VARCHAR(20)", "billing")
        add_column_if_missing("agenda_events", "insurer VARCHAR(120)", "insurer")

        # PRODUCTS
        add_column_if_missing("products", "code VARCHAR(64)", "code")
        add_column_if_missing("products", "category VARCHAR(80)", "category")
        add_column_if_missing("products", "application_route VARCHAR(80)", "application_route")
        add_column_if_missing("products", "min_stock INTEGER DEFAULT 0", "min_stock")
        add_column_if_missing("products", "user_id INTEGER", "user_id")
        add_column_if_missing("products", "purchase_price FLOAT", "purchase_price")
        add_column_if_missing("products", "sale_price FLOAT", "sale_price")
        add_column_if_missing("products", "quantity INTEGER DEFAULT 0", "quantity")
        add_column_if_missing("products", "status VARCHAR(20) DEFAULT 'Ativo'", "status")
        add_column_if_missing("products", "created_at TIMESTAMP", "created_at")

        # DOCTORS
        add_column_if_missing("doctors", "user_id INTEGER", "user_id")
        add_column_if_missing("doctors", "crm VARCHAR(50)", "crm")
        add_column_if_missing("doctors", "email VARCHAR(120)", "email")
        add_column_if_missing("doctors", "phone VARCHAR(50)", "phone")
        add_column_if_missing("doctors", "specialty VARCHAR(120)", "specialty")

        # PDF_FILES
        add_column_if_missing("pdf_files", "patient_id INTEGER", "patient_id")
        add_column_if_missing("pdf_files", "consult_id INTEGER", "consult_id")

def _save_pdf_bytes_to_db(*, owner_user_id: int, patient_id: Optional[int], consult_id: Optional[int],
                          original_name: str, data: bytes, kind: str) -> int:
    """
    Guarda o PDF em SecureFile (blob) + PdfFile (metadados/vínculo) e retorna o id do PdfFile.
    """
    unique_name = f"{secure_filename(os.path.splitext(original_name)[0])}_{int(datetime.utcnow().timestamp())}.pdf"
    sf = SecureFile(
        owner_user_id=owner_user_id,
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
    Envia um PDF armazenado (verifica owner).
    """
    u = current_user()
    pf = PdfFile.query.get_or_404(pdf_file_id)
    sf = pf.secure_file
    if not sf or (sf.owner_user_id is not None and sf.owner_user_id != u.id):
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
    return render_template("admin_users.html", users=all_users)


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
    """Converte um datetime UTC para horário de Brasília (America/Sao_Paulo)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        # assume que vem em UTC
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(ZoneInfo("America/Sao_Paulo"))

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

def _delete_securefile_if_owned(file_id: int, owner_user_id: int):
    try:
        sf = SecureFile.query.get(file_id)
        if sf and (sf.owner_user_id is None or sf.owner_user_id == owner_user_id):
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
    Regras:
      - Usuário com username "admin" tem acesso vitalício (bypass).
      - Se user.plan_status == 'paid' e plan_expires_at >= agora => permitido.
      - Se user.trial_until >= agora => permitido.
      - Caso contrário redireciona para a página de planos (/planos) para pagamento.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        u = get_logged_user()
        if not u:
            return redirect(url_for('login'))
        g.user = u

        # Admin sempre permite (acesso vitalício)
        try:
            uname = getattr(u, "username", "") or ""
        except Exception:
            uname = ""

        if uname.lower() == "admin":
            # admin tem acesso vitalício
            return f(*args, **kwargs)

        # verificar se está em trial válido
        now = datetime.utcnow()
        trial_until = getattr(u, "trial_until", None)
        plan_status = getattr(u, "plan_status", None)
        plan_expires = getattr(u, "plan_expires_at", None)

        # Usuário pago com plan_expires_at em futuro
        if plan_status == "paid":
            if (plan_expires is None) or (plan_expires and plan_expires >= now):
                return f(*args, **kwargs)

        # Usuário em trial válido
        if trial_until and trial_until >= now:
            return f(*args, **kwargs)

        # Caso contrário: sem trial válido nem pagamento -> bloquear acesso
        # Redireciona para a página de planos / preços (página de compra)
        flash("Seu período de teste de 14 dias expirou. Faça a assinatura para continuar usando o sistema.", "trial_expired")
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

# ------------------------------------------------------------------------------
# Registering (Blueprint com verificação de e-mail e agendamentos)
# ------------------------------------------------------------------------------
from flask import Blueprint
from itsdangerous import URLSafeTimedSerializer
from datetime import datetime, timedelta

auth_bp = Blueprint('auth', __name__, template_folder='templates/auth')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        confirm = request.form.get('confirm') or ''

        import re
        # ------------------------------
        # 1️⃣ Validação de senha
        # ------------------------------
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

        # ------------------------------
        # 2️⃣ Confirmação de senha
        # ------------------------------
        if password != confirm:
            return render_template("register.html",
                                   error_message="As senhas não coincidem.")

        # ------------------------------
        # 3️⃣ Verificar se username/email já existem (case-insensitive p/ email)
        # ------------------------------
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

        # ------------------------------
        # 4️⃣ Criar token de verificação
        # ------------------------------
        s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        token = s.dumps(
            {
                'username': username,
                'email': email,
                'password_hash': generate_password_hash(password)
            },
            salt='email-confirm'
        )

        confirm_url = url_for('auth.verify_email', token=token, _external=True)

        # ------------------------------
        # 5️⃣ Montar e enviar o e-mail com a logo 1.png inline
        # ------------------------------
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
                "path": os.path.join("static", "images", "1.png"),  # ✅ usa 1.png
                "cid": "logo"
            }]
        )

        # ------------------------------
        # 6️⃣ Mensagem para o usuário
        # ------------------------------
        success_message = (
            "Cadastro realizado com sucesso! "
            f"Abra seu e-mail <strong>{email}</strong> e clique no link enviado para confirmar sua conta. "
            "Confira também a pasta SPAM."
        )
        return render_template("register.html", success_message=success_message)

    # GET
    return render_template("register.html")

@auth_bp.route('/verify_email/<token>')
def verify_email(token):
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        data = s.loads(token, salt='email-confirm', max_age=3600*24)
    except (SignatureExpired, BadSignature):
        abort(400)

    now = datetime.utcnow()

    new_user = User(
        username=data['username'],
        email=data['email'].lower(),
        password_hash=data['password_hash'],
        created_at=now,
        plan_status='trial',          # <- controle simples de status
        trial_until=now + timedelta(days=14),
        plan_expires_at=None
    )
    db.session.add(new_user)
    db.session.commit()

    # agenda os e-mails de trial (4, 7, 10, 14 e 15 dias)
    try:
        schedule_trial_emails(new_user.id)
    except Exception:
        current_app.logger.exception("Falha ao agendar e-mails de trial")

    flash('Conta confirmada com sucesso. Agora você pode entrar.', 'success')
    return redirect(url_for('login'))

def schedule_trial_emails(user_id: int) -> None:
    """
    Agenda e-mails automáticos para +4, +7, +10, +14 e +15 dias após a criação da conta.
    """
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
                "path": os.path.join("static", "images", "1.png"),  # ✅ usa 1.png também nos trials
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
    total_patients = Patient.query.filter_by(owner_user_id=u.id).count()
    total_consults = (
        Consult.query
        .join(Patient, Patient.id == Consult.patient_id)
        .filter(Patient.owner_user_id == u.id)
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
        .filter(Patient.owner_user_id == u.id)
        .group_by(Consult.patient_id)
        .all()
    )
    first_by_patient = {row.pid: row.first_date for row in first_consult_q}

    active_patients_30 = (
        db.session.query(Consult.patient_id)
        .join(Patient, Patient.id == Consult.patient_id)
        .filter(
            Patient.owner_user_id == u.id,
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
        .filter(Patient.owner_user_id == u.id)
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
        trial_active=u.trial_until and u.trial_until >= datetime.utcnow(),
    )

# ------------------------------------------------------------------------------
# Compra de Pacotes
# ------------------------------------------------------------------------------
@app.route('/purchase', methods=['GET', 'POST'])
@login_required
def purchase():
    """
    Mantém a lógica de compra de pacotes, mas renderiza a página unificada
    e processa POST de pacotes normalmente.
    """
    if request.method == 'POST':
        pacote = request.form.get('package', '')
        valor = {'50': 120, '150': 300, '500': 950}.get(pacote)
        if not valor:
            flash('Selecione um pacote válido.', 'warning')
            return redirect(url_for('payments'))
        from mercado_pago import generate_payment_link
        link = generate_payment_link(pacote, valor)
        return redirect(link or url_for('payments'))
    
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
    trial_until = getattr(u, "trial_until", None)
    if trial_until:
        remaining_td = trial_until - now
        remaining_days = max(0, remaining_td.days)
        trial_active = (trial_until >= now)
    else:
        remaining_days = 0
        trial_active = False

    # status pago?
    plan_status = getattr(u, "plan_status", None) or "inactive"
    plan_expires_at = getattr(u, "plan_expires_at", None)
    is_paid_active = False
    if plan_status == "paid":
        if (plan_expires_at is None) or (plan_expires_at and plan_expires_at >= now):
            is_paid_active = True

    # admin bypass
    is_admin = (getattr(u, "username", "").lower() == "admin")

    return render_template(
        'account.html',
        user=u,
        trial_active=trial_active,
        trial_remaining_days=remaining_days,
        plan_status=plan_status,
        plan_expires_at=plan_expires_at,
        is_paid_active=is_paid_active,
        is_admin=is_admin
    )

@app.route('/subscribe', methods=['GET', 'POST'])
@login_required
def subscribe():
    """
    Fluxo simples de assinatura:
      - GET: mostra página de preços (ou redireciona para /planos)
      - POST: marca usuário como 'paid' e define plan_expires_at = agora + 30 dias
    Observação: aqui é o lugar para integrar MercadoPago / Stripe / gateway real.
    """
    u = current_user()
    now = datetime.utcnow()

    # Se vier POST -> "confirmar pagamento" (simulação)
    if request.method == "POST":
        # Aqui você integraria com MercadoPago/Stripe.
        # Simulação: marcar como pago por 30 dias
        u.plan_status = "paid"
        u.plan_expires_at = now + timedelta(days=30)
        # remover trial (opcional)
        u.trial_until = None
        db.session.commit()
        flash("Pagamento registrado. Obrigado! Sua assinatura foi ativada por 30 dias.", "success")
        return redirect(url_for('account'))

    # GET -> renderizar a página de preços / checkout
    # Se já está pago, redireciona para a conta
    if (u.plan_status == "paid") and (not u.plan_expires_at or u.plan_expires_at >= now):
        flash("Sua assinatura já está ativa.", "info")
        return redirect(url_for('account'))

    # renderiza a página de preços (ou template de checkout)
    return render_template('prices.html')

@app.route('/subscribe/pay')
@login_required
def subscribe_pay():
    u = current_user()
    from mercado_pago import generate_subscription_link
    link = generate_subscription_link(u.id)
    return redirect(link or url_for('payments'))

@app.route('/subscription/success')
def subscription_success():
    user_id = request.args.get('metadata[user_id]')
    if user_id:
        user = User.query.get(int(user_id))
        if user:
            user.plan_status = 'paid'
            user.plan_expires_at = datetime.utcnow() + timedelta(days=30)
            user.trial_until = None
            db.session.commit()
    flash("Assinatura ativada por 30 dias.", "success")
    return redirect(url_for('account'))

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
    birthdate_str = (request.form.get("birthdate") or "").strip()

    if name:
        u.name = name

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

        # remove SecureFile anterior se houver
        old = (u.profile_image or "").replace("\\", "/")
        old_sid = _extract_securefile_id_from_url(old)
        if old_sid:
            _delete_securefile_if_owned(old_sid, u.id)

        new_name = f"user_{u.id}_{int(_time.time())}.{ext}"
        sf = SecureFile(
            owner_user_id=u.id,
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
    from prescription import analyze_pdf
    u = current_user()

    if request.method == 'GET':
        success    = request.args.get('success', type=int)
        success_id = request.args.get('success_id', type=int)
        error      = request.args.get('error')
        return render_template(
            'upload.html',
            success=success,
            success_id=success_id,
            error=error,
            notifications_unread=0
        )

 # ==========================
    # 1) INSERÇÃO MANUAL
    # ==========================
    if request.form.get('manual_entry') == '1':
        name_form       = (request.form.get('name') or '').strip()
        age_s           = (request.form.get('age') or '').strip()  # (não usado agora, mantém)
        cpf_form        = (request.form.get('cpf') or '').strip()
        gender_form     = (request.form.get('gender') or '').strip()
        phone_form      = (request.form.get('phone') or '').strip()
        doctor_form     = (request.form.get('doctor') or '').strip()
        doctor_phone_in = (request.form.get('doctor_phone') or '').strip()
        lab_results     = (request.form.get('lab_results') or '').strip()

        # Opções de envio (checkboxes)
        send_doctor  = (request.form.get('send_doctor') == '1')
        send_patient = (request.form.get('send_patient') == '1')

        if not lab_results:
            return redirect(url_for('upload', error="Digite os resultados no campo de texto."))

        # references.json (single source)
        try:
            refs_path = _project_references_json()
        except FileNotFoundError as e:
            print("[PDF] references.json missing:", e)
            return redirect(url_for('upload', error=str(e)))

        try:
            dgn, rx, name_ai, gender_ai, age_ai, cpf_ai, phone_ai, doctor_ai = analyze_pdf(
                lab_results, references_path=refs_path, manual=True
            )
        except Exception as e:
            print("[PDF] manual analyze error:", e)
            return redirect(url_for('upload', error="Falha ao analisar o texto manual."))

        name        = name_form or name_ai or 'Paciente (manual)'
        gender      = gender_form or gender_ai or None
        cpf         = cpf_form or cpf_ai or ''
        phone       = phone_form or phone_ai or ''
        doctor_name = doctor_form or doctor_ai or ''
        doctor_phone= doctor_phone_in  # prioridade do formulário

        # Paciente por CPF
        p = Patient.query.filter_by(owner_user_id=u.id, cpf=cpf).first() if cpf else None
        if p:
            if name and not (p.name or '').strip():   p.name = name
            if gender and not (p.sex or '').strip():  p.sex = gender
            if phone and not (p.phone_primary or '').strip(): p.phone_primary = phone
        else:
            p = Patient(
                owner_user_id=u.id,
                name=name,
                birthdate=None,
                sex=gender or None,
                email=None,
                cpf=cpf or None,
                notes=None,
                profile_image=DEFAULT_PATIENT_IMAGE,
                phone_primary=phone,
                phone_secondary=None
            )
            db.session.add(p)
        db.session.commit()

        # Resolve doctor (preferindo criar/atualizar com telefone se informado)
        doctor_id = None
        if doctor_name:
            # limita ao escopo do usuário, se houver coluna user_id
            base = Doctor.query
            if hasattr(Doctor, 'user_id'):
                base = base.filter(Doctor.user_id == u.id)
            doc = base.filter(Doctor.name.ilike(doctor_name)).first()
            if not doc:
                d_kwargs = dict(name=doctor_name, phone=(doctor_phone or None))
                if hasattr(Doctor, 'user_id'):
                    d_kwargs['user_id'] = u.id
                doc = Doctor(**d_kwargs)
                db.session.add(doc)
                db.session.commit()
            else:
                if doctor_phone and not (doc.phone or '').strip():
                    doc.phone = doctor_phone
                    db.session.commit()
            doctor_id = doc.id
        if not doctor_id:
            doctor_id = get_or_create_default_doctor()

        diagnosis     = (dgn or "").strip()
        prescriptions = (rx or "").strip()
        notes_blob = diagnosis + "\n\nPrescrição:\n" + prescriptions

        c = Consult(
            patient_id=p.id,
            date=datetime.today().date(),
            time=None,
            notes=notes_blob
        )
        if hasattr(c, "doctor_id"):
            c.doctor_id = doctor_id

        db.session.add(c)
        db.session.commit()

        # === Envio automático via WhatsApp, se marcado ===
        try:
            if send_doctor or send_patient:
                filename = f"Resultado_{(p.name or 'Paciente').replace(' ', '_')}.pdf"
                pdf_bytes = generate_result_pdf_bytes(
                    patient=p,
                    diagnostic_text=diagnosis,
                    prescription_text=prescriptions,
                    doctor_display_name=(getattr(u, "name", None) or u.username)
                )
                # Enviar ao médico
                if send_doctor:
                    target_phone = doctor_phone or ""
                    # fallback: se o médico existir com phone cadastrado
                    if not target_phone and doctor_id:
                        try:
                            d = Doctor.query.get(doctor_id)
                            target_phone = (getattr(d, "phone", "") or "").strip()
                        except Exception:
                            pass
                    if target_phone:
                        try_send_whatsapp_pdf(target_phone, pdf_bytes, filename)
                    else:
                        print("[WA] sem telefone do médico para envio.")
                # Enviar ao paciente
                if send_patient:
                    target_phone = (p.phone_primary or "").strip()
                    if target_phone:
                        try_send_whatsapp_pdf(target_phone, pdf_bytes, filename)
                    else:
                        print("[WA] sem telefone do paciente para envio.")
        except Exception as e:
            print("[WA] erro no pipeline de envio:", e)

        return redirect(url_for('upload', success=1, success_id=p.id))

    # ==========================
    # 2) UPLOAD DE PDF (no DB)
    # ==========================
    file = request.files.get('pdf_file') or request.files.get('file') or request.files.get('pdf')
    send_doctor  = (request.form.get('send_doctor') == '1')
    send_patient = (request.form.get('send_patient') == '1')
    doctor_phone_in = (request.form.get('doctor_phone') or '').strip()
    patient_phone_in = (request.form.get('patient_phone') or '').strip()

    if not file or not (file.filename and file.filename.strip()):
        return redirect(url_for('upload', error="Nenhum arquivo selecionado."))

    raw_name = file.filename
    if not raw_name.lower().endswith('.pdf'):
        return redirect(url_for('upload', error="Tipo de arquivo não permitido. Envie um PDF."))

    # --- previne 'Unbound' do Pylance e falhas silenciosas ---
    content: bytes = b""
    pf: Optional[PdfFile] = None
    tmp_pdf: Optional[str] = None
    tmp_refs: Optional[str] = None

    try:
        content = file.read() or b""
        if not content:
            return redirect(url_for('upload', error="PDF vazio ou inválido."))

        size = len(content)
        filename_safe = secure_filename(raw_name)
        unique_name = f"{os.path.splitext(filename_safe)[0]}_{int(datetime.utcnow().timestamp())}.pdf"

        # Guarda no DB
        sf = SecureFile(
            owner_user_id=u.id,
            kind="upload_pdf",
            filename=unique_name,
            mime_type="application/pdf",
            size_bytes=size,
            data=content
        )
        db.session.add(sf)
        db.session.flush()  # precisa do sf.id

        pf = PdfFile(
            filename=unique_name,
            original_name=raw_name,
            size_bytes=size,
            secure_file_id=sf.id
        )
        db.session.add(pf)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print("[UPLOAD] erro ao persistir PDF no DB:", e)
        return redirect(url_for('upload', error="Falha ao salvar o arquivo."))

    # ---------- ANÁLISE ----------
    # Use exatamente os bytes persistidos (mais robusto que depender do stream original)
    try:
        persisted_bytes = pf.secure_file.data if (pf and pf.secure_file and pf.secure_file.data) else content
    except Exception:
        persisted_bytes = content

    # Use references.json directly
    try:
        refs_path = _project_references_json()
    except FileNotFoundError as e:
        print("[PDF] references.json missing:", e)
        return redirect(url_for('upload', error=str(e)))

    tmp_pdf = None
    try:
        fd, tmp_pdf = tempfile.mkstemp(prefix="up_", suffix=".pdf")
        with os.fdopen(fd, "wb") as fh:
            fh.write(persisted_bytes)

        dgn, rx, name_ai, gender_ai, age_ai, cpf_ai, phone_ai, doctor_ai = analyze_pdf(
            tmp_pdf, references_path=refs_path, manual=False
        )
    except Exception as e:
        print("[PDF] analyze error:", e)
        dgn, rx, name_ai, gender_ai, age_ai, cpf_ai, phone_ai, doctor_ai = (
            "Error reading PDF or references.", "", "", "", 0, "", "", ""
        )
    finally:
        try:
            if tmp_pdf and os.path.exists(tmp_pdf):
                os.remove(tmp_pdf)
        except Exception:
            pass

    diagnosis     = (dgn or "").strip()
    prescriptions = (rx or "").strip()
    name          = (name_ai or "").strip()
    gender        = (gender_ai or "").strip() or None
    cpf           = (cpf_ai or "").strip()
    phone         = (phone_ai or "").strip()
    doctor_name   = (doctor_ai or "").strip()

    # Paciente por CPF
    p = Patient.query.filter_by(owner_user_id=u.id, cpf=cpf).first() if cpf else None
    if p:
        if name and not (p.name or '').strip():   p.name = name
        if gender and not (p.sex or '').strip():  p.sex = gender
        if phone and not (p.phone_primary or '').strip(): p.phone_primary = phone
    else:
        p = Patient(
            owner_user_id=u.id,
            name=(name or f"Paciente ({datetime.now().strftime('%d/%m/%Y %H:%M')})"),
            birthdate=None,
            sex=(gender or None),
            email=None,
            cpf=(cpf or None),
            notes=None,
            profile_image=DEFAULT_PATIENT_IMAGE,
            phone_primary=(phone or ''),
            phone_secondary=None
        )
        db.session.add(p)
    db.session.commit()

    # Resolve doctor_id SEMPRE
    doctor_id = None
    if doctor_name:
        doc = Doctor.query.filter(Doctor.name.ilike(doctor_name)).first()
        if doc:
            doctor_id = doc.id
    if not doctor_id:
        doctor_id = get_or_create_default_doctor()

    notes_blob = diagnosis + "\n\nPrescrição:\n" + prescriptions

    c = Consult(
        patient_id=p.id,
        date=datetime.today().date(),
        time=None,
        notes=notes_blob
    )
    if hasattr(c, "doctor_id"):
        c.doctor_id = doctor_id

    db.session.add(c)
    db.session.commit()

    # === Envio automático via WhatsApp, se marcado no upload ===
    try:
        if send_doctor or send_patient:
            filename = f"Resultado_{(p.name or 'Paciente').replace(' ', '_')}.pdf"
            pdf_bytes = generate_result_pdf_bytes(
                patient=p,
                diagnostic_text=diagnosis,
                prescription_text=prescriptions,
                doctor_display_name=(getattr(u, "name", None) or u.username)
            )
            # Enviar ao médico
            if send_doctor:
                target_phone = doctor_phone_in
                if not target_phone and doctor_id:
                    try:
                        d = Doctor.query.get(doctor_id)
                        target_phone = (getattr(d, "phone", "") or "").strip()
                    except Exception:
                        pass
                if target_phone:
                    try_send_whatsapp_pdf(target_phone, pdf_bytes, filename)
                else:
                    print("[WA] sem telefone do médico para envio.")
            # Enviar ao paciente
            if send_patient:
                target_phone = patient_phone_in or (p.phone_primary or "").strip()
                if target_phone:
                    try_send_whatsapp_pdf(target_phone, pdf_bytes, filename)
                else:
                    print("[WA] sem telefone do paciente para envio.")
    except Exception as e:
        print("[WA upload] erro no pipeline de envio:", e)

    # vincula o PdfFile ao paciente/consulta, se existir
    try:
        if pf is not None:
            pf.patient_id = p.id
            pf.consult_id = c.id
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        print("[UPLOAD] falha ao vincular PdfFile ao paciente/consulta:", e)

    return redirect(url_for('upload', success=1, success_id=p.id))

@app.route('/download_pdf/<int:patient_id>')
@login_required
def download_pdf(patient_id):
    from weasyprint import HTML
    u = current_user()
    patient = Patient.query.get_or_404(patient_id)
    if patient.owner_user_id != u.id:
        abort(403)

    consults = Consult.query.filter_by(patient_id=patient_id).order_by(Consult.id.asc()).all()
    if consults:
        latest = consults[-1].notes or ""
        parts = latest.split("Prescrição:\n", 1)
        diagnostic_text  = parts[0].strip()
        prescription_text = parts[1].strip() if len(parts) > 1 else ""
        latest_consult_id = consults[-1].id
    else:
        diagnostic_text  = "Nenhuma consulta registrada."
        prescription_text = ""
        latest_consult_id = None

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

    html_str = render_template(
        "result_pdf.html",
        patient_info=patient_info,
        diagnostic_text=diagnostic_text,
        prescription_text=prescription_text,
        doctor_name=(getattr(u, "name", None) or u.username),
    )

    pdf_io = BytesIO()
    pdf_ok = False

    # 1) Tenta WeasyPrint
    try:
        HTML(string=html_str, base_url=current_app.root_path).write_pdf(pdf_io)
        pdf_io.seek(0)
        pdf_ok = True
    except Exception as e:
        print("[PDF] WeasyPrint error, tentando ReportLab:", e)

    # 2) Fallback ReportLab
    if not pdf_ok:
        try:
            from reportlab.lib.pagesizes import A4  # type: ignore
            from reportlab.pdfgen import canvas    # type: ignore
            from reportlab.lib.units import mm     # type: ignore
            from reportlab.lib.utils import ImageReader  # type: ignore

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
                    c.drawImage(img, width - target_w - 15*mm, height - target_h - 15*mm,
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
                    c.showPage(); y = height - 20 * mm

            y -= 4 * mm
            c.setFont("Times-Bold", 12)
            c.drawString(20 * mm, y, "Prescrição:")
            y -= 7 * mm
            c.setFont("Times-Roman", 11)
            for ln in (prescription_text or "—").splitlines():
                c.drawString(22 * mm, y, ln)
                y -= 6 * mm
                if y < 40 * mm:
                    c.showPage(); y = height - 20 * mm

            c.setFont("Times-Roman", 11)
            c.line(60 * mm, 25 * mm, 150 * mm, 25 * mm)
            c.drawCentredString(105 * mm, 20 * mm, getattr(u, "name", None) or u.username)

            c.showPage()
            c.save()
            pdf_io.seek(0)
            pdf_ok = True
        except Exception as e2:
            return jsonify(success=False, error=f"Falha ao gerar PDF: {e2}"), 500

    # === Persistir o PDF gerado no banco (🔗 já vinculado ao paciente/consulta) ===
    try:
        pdf_bytes = pdf_io.getvalue()
        display_name = f"Resultado_{(patient.name or 'Paciente').replace(' ', '_')}.pdf"
        _save_pdf_bytes_to_db(
            owner_user_id=u.id,
            patient_id=patient.id,
            consult_id=latest_consult_id,
            original_name=display_name,
            data=pdf_bytes,
            kind="result_pdf",
        )
    except Exception as e:
        db.session.rollback()
        print("[PDF] erro ao salvar PDF gerado no DB:", e)

    download_name = f"Resultado_{(patient.name or 'Paciente').replace(' ', '_')}.pdf"
    pdf_io.seek(0)
    return send_file(pdf_io, as_attachment=True, download_name=download_name, mimetype="application/pdf")

@app.route('/files/pdf/<int:pdf_id>')
@login_required
def serve_pdf(pdf_id):
    return _serve_pdf_from_db(pdf_id)

@app.route('/patients/<int:patient_id>/pdfs', methods=['GET'])
@login_required
def patient_pdfs(patient_id: int):
    u = current_user()
    p = Patient.query.get_or_404(patient_id)
    if p.owner_user_id != u.id:
        abort(403)

    # traz todos os PDFs do paciente (uploads e resultados)
    rows = (
        db.session.query(PdfFile, SecureFile)
        .join(SecureFile, PdfFile.secure_file_id == SecureFile.id)
        .filter(
            PdfFile.patient_id == patient_id,
            SecureFile.owner_user_id == u.id
        )
        .order_by(PdfFile.uploaded_at.desc())
        .all()
    )

    out = []
    for pf, sf in rows:
        out.append({
            "id": pf.id,
            "original_name": pf.original_name or pf.filename,
            "size_bytes": pf.size_bytes,
            "uploaded_at": pf.uploaded_at.isoformat(),
            "kind": sf.kind,
            "download_url": url_for('serve_pdf', pdf_id=pf.id)
        })
    return jsonify(out)

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

    # Consultas (somente leitura) — filtradas pelo range se disponível
    cq = (
        Consult.query
        .join(Patient, Patient.id == Consult.patient_id)
        .filter(Patient.owner_user_id == u.id)
    )
    if start_dt and end_dt:
        cq = cq.filter(Consult.date >= start_dt.date(), Consult.date <= end_dt.date())

    for c in cq.all():
        if c.time:
            start = datetime.combine(c.date, c.time).isoformat()
            ev = {"title": c.notes or "Consulta", "start": start, "allDay": False}
        else:
            ev = {"title": c.notes or "Consulta", "start": c.date.isoformat(), "allDay": True}
        ev.update({
            "className": "patient-event",
            "extendedProps": {"type": "consulta"},
            "editable": False,  # <- impede arrastar/redimensionar
        })
        events.append(ev)

    return jsonify(events)


@app.route('/api/add_event', methods=['POST'])
@login_required
def api_add_event():
    """
    Cria um AgendaEvent. Aceita start/end com 'Z' ou offset.
    """
    u = current_user()
    data = request.get_json(silent=True) or {}

    title   = (data.get('title') or '').strip()
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

    end_dt = _parse_iso_to_naive_utc(end_s) if end_s else None
    if end_s and not end_dt:
        return jsonify(success=False, error="Formato de data/hora inválido (end)."), 400
    if not end_dt:
        end_dt = start_dt + timedelta(hours=1)

    ev = AgendaEvent(
        user_id=u.id,
        title=title,
        start=start_dt,
        end=end_dt,
        notes=(notes or None),
        type=(type_ or None),
        billing=(billing or None),
        insurer=(insurer or None),
    )
    db.session.add(ev)
    db.session.commit()
    return jsonify(success=True, event_id=ev.id), 201


# Alias opcional: permite criar também em POST /api/events
@app.route('/api/events', methods=['POST'])
@login_required
def api_create_event_alias():
    return api_add_event()


@app.route('/api/events/<int:event_id>', methods=['PUT', 'DELETE'])
@login_required
def api_event_mutation(event_id: int):
    """
    PUT: atualiza campos; aceita start/end ISO com 'Z' ou offset.
    DELETE: remove o evento do usuário atual.
    """
    u = current_user()
    ev = AgendaEvent.query.get_or_404(event_id)
    if getattr(ev, 'user_id', None) != u.id:
        abort(403)

    if request.method == 'DELETE':
        db.session.delete(ev)
        db.session.commit()
        return jsonify(success=True)

    # PUT
    data = request.get_json(silent=True) or {}

    # Datas
    if 'start' in data:
        start_dt = _parse_iso_to_naive_utc((data.get('start') or '').strip())
        if not start_dt:
            return jsonify(success=False, error="Formato de data/hora inválido para 'start'."), 400
        ev.start = start_dt

    if 'end' in data:
        end_val = (data.get('end') or '').strip()
        if end_val:
            end_dt = _parse_iso_to_naive_utc(end_val)
            if not end_dt:
                return jsonify(success=False, error="Formato de data/hora inválido para 'end'."), 400
            ev.end = end_dt
        else:
            ev.end = None

    # Strings simples
    for key in ('title', 'notes', 'type', 'billing', 'insurer'):
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
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()

        # aceita dd/mm/aaaa (preferencial) e fallback yyyy-mm-dd
        birthdate_s = (request.form.get('birthdate') or '').strip()
        birthdate = None
        if birthdate_s:
            for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
                try:
                    birthdate = datetime.strptime(birthdate_s, fmt).date()
                    break
                except Exception:
                    continue

        sex   = (request.form.get('sex') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        cpf   = (request.form.get('cpf') or request.form.get('document') or '').strip().replace('.', '').replace('-', '')
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

        # (opcional) se quiser vincular um médico do catálogo:
        doctor_id = request.form.get('doctor_id')
        try:
            doctor_id = int(doctor_id) if doctor_id else None
        except Exception:
            doctor_id = None

        missing = []
        if not name: missing.append('name')
        if not birthdate: missing.append('birthdate')
        if not sex: missing.append('sex')
        if not phone_pri: missing.append('phone_primary')
        if missing:
            flash("Preencha todos os campos obrigatórios.", "warning")
            return redirect(url_for('register_patient'))

        profile_rel = DEFAULT_PATIENT_IMAGE
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
                profile_rel = os.path.relpath(dest_path, STATIC_DIR).replace("\\", "/")

        p = Patient(
            owner_user_id=u.id,
            doctor_id=doctor_id,
            name=name,
            birthdate=birthdate,
            sex=sex or None,
            email=email or None,
            cpf=cpf or None,
            notes=notes or None,
            profile_image=profile_rel or DEFAULT_PATIENT_IMAGE,
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

    return render_template('register_patient.html')

@app.route('/catalog')
@login_required
def catalog():
    u = current_user()
    search = request.args.get('search', '').strip().lower()
    status = request.args.get('status', '').strip()

    patients = Patient.query.filter_by(owner_user_id=u.id).all()
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
# Editar Paciente (com upload de foto usando SecureFile) ✅
# ------------------------------------------------------------------------------
@app.route('/edit_patient/<int:patient_id>', methods=['GET', 'POST'])
@login_required
def edit_patient(patient_id):
    import time as _time

    u = current_user()
    patient = Patient.query.get_or_404(patient_id)
    if patient.owner_user_id != u.id:
        abort(403)

    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()

        # aceita dd/mm/aaaa e yyyy-mm-dd
        birthdate_s = (request.form.get('birthdate') or '').strip()
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

        missing = []
        if not name: missing.append('name')
        if not birthdate: missing.append('birthdate')
        if not sex: missing.append('sex')
        if not phone_pri: missing.append('phone_primary')
        if missing:
            flash("Preencha todos os campos obrigatórios.", "warning")
            return redirect(url_for('edit_patient', patient_id=patient.id))

        # ==============
        # Upload da foto (opcional) — via SecureFile
        # ==============
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

            # Remove imagem anterior: SecureFile OU arquivo físico legado
            old_rel = (patient.profile_image or "").replace("\\", "/")
            old_sid = _extract_securefile_id_from_url(old_rel)
            if old_sid:
                _delete_securefile_if_owned(old_sid, u.id)
            else:
                # compat: pode ter sido salvo em static/uploads/patients
                _safe_remove_patient_photo(old_rel)

            new_name = f"patient_{u.id}_{int(_time.time())}.{ext}"
            sf = SecureFile(
                owner_user_id=u.id,
                kind="patient_profile_image",
                filename=new_name,
                mime_type=file.mimetype or f"image/{ext}",
                size_bytes=len(content),
                data=content,
            )
            db.session.add(sf)
            db.session.flush()
            patient.profile_image = f"/files/img/{sf.id}"

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

@app.route('/patient_result/<int:patient_id>')
@login_required
def patient_result(patient_id):
    u = current_user()
    patient = Patient.query.get_or_404(patient_id)
    if patient.owner_user_id != u.id:
        abort(403)

    consults = Consult.query.filter_by(patient_id=patient_id).order_by(Consult.id.asc()).all()
    if consults:
        latest = consults[-1].notes or ""
        parts = latest.split("Prescrição:\n", 1)
        diagnostic_text  = parts[0].strip()
        prescription_text = parts[1].strip() if len(parts) > 1 else ""
    else:
        diagnostic_text  = "Nenhuma consulta registrada."
        prescription_text = ""

    return render_template(
        'result.html',
        patient=patient,
        diagnostic_text=diagnostic_text,
        prescription_text=prescription_text,
        doctor_name=getattr(u, "name", u.username)
    )

# ------------------------------------------------------------------------------
# Paciente – Foto de perfil (upload/remover)
# ------------------------------------------------------------------------------
def _patient_photos_dir():
    dest_dir = os.path.join(STATIC_DIR, "uploads", "patients")
    os.makedirs(dest_dir, exist_ok=True)
    return dest_dir

def _safe_remove_patient_photo(rel_path: str):
    """Remove o arquivo antigo com segurança (apenas dentro de static/uploads/patients)."""
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
    """Salva foto do paciente em SecureFile e referencia via /files/img/<id>."""
    import time as _time

    u = current_user()
    p = Patient.query.get_or_404(patient_id)
    if p.owner_user_id != u.id:
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

    # Remove imagem anterior (SecureFile ou arquivo estático legado)
    old_rel = (p.profile_image or "").replace("\\", "/")
    old_sid = _extract_securefile_id_from_url(old_rel)
    if old_sid:
        _delete_securefile_if_owned(old_sid, u.id)
    else:
        _safe_remove_patient_photo(old_rel)

    new_name = f"patient_{u.id}_{int(_time.time())}.{ext}"
    sf = SecureFile(
        owner_user_id=u.id,
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
    """Volta à imagem padrão e apaga a atual do SecureFile (se for DB) ou arquivo físico legado."""
    u = current_user()
    p = Patient.query.get_or_404(patient_id)
    if p.owner_user_id != u.id:
        abort(403)

    old_rel = (p.profile_image or "").replace("\\", "/")
    old_sid = _extract_securefile_id_from_url(old_rel)
    if old_sid:
        _delete_securefile_if_owned(old_sid, u.id)
    else:
        _safe_remove_patient_photo(old_rel)

    p.profile_image = DEFAULT_PATIENT_IMAGE
    db.session.commit()

    flash("Foto de perfil removida.", "info")
    return redirect(url_for('edit_patient', patient_id=p.id))

@app.route('/files/img/<int:file_id>')
@login_required
def serve_image(file_id: int):
    u = current_user()
    sf = SecureFile.query.get_or_404(file_id)
    if sf.owner_user_id is not None and sf.owner_user_id != u.id:
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
    u = current_user()
    patient = Patient.query.get_or_404(patient_id)
    if patient.owner_user_id != u.id:
        abort(403)
    return render_template('patient_info.html', patient=patient)

# /api/add_patient — criação via JSON (ex.: fetch/AJAX). Persiste no Postgres igual.
@app.route('/api/add_patient', methods=['POST'])
@login_required
def api_add_patient():
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

    # opcional: vínculo com médico
    doctor_id = data.get("doctor_id")
    try:
        doctor_id = int(doctor_id) if doctor_id else None
    except Exception:
        doctor_id = None

    if not (name and birthdate_s and sex and phone_pri):
        return jsonify(success=False, error='Campos obrigatórios: nome, data de nascimento, sexo, celular.'), 400

    # aceita dd/mm/aaaa (preferencial) e fallback yyyy-mm-dd
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

    p = Patient(
        owner_user_id=u.id,
        doctor_id=doctor_id,
        name=name,
        birthdate=birthdate,
        sex=sex,
        email=email or None,
        cpf=cpf or None,
        notes=notes or None,
        profile_image=DEFAULT_PATIENT_IMAGE,
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
    u = current_user()
    p = Patient.query.get_or_404(patient_id)
    if p.owner_user_id != u.id:
        abort(403)
    Consult.query.filter_by(patient_id=patient_id).delete(synchronize_session=False)
    db.session.delete(p)
    db.session.commit()
    flash('Paciente removido.', 'info')
    return redirect(url_for('catalog'))

@app.route('/toggle_patient_status/<int:patient_id>/<new_status>', methods=['GET', 'POST'])
@login_required
def toggle_patient_status(patient_id, new_status):
    u = current_user()
    p = Patient.query.get_or_404(patient_id)
    if p.owner_user_id != u.id:
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
        # relaciona os fornecedores diretamente
        q.suppliers = selected_suppliers  # type: ignore

        db.session.add(q)
        db.session.commit()
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
        p.quantity = new_qty
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
        type_      = (data.get('type') or '').strip().lower()
    else:
        product_id = _to_int(request.form.get('product_id'), 0)
        qty        = _to_int(request.form.get('quantity'), 0)
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
        qty =  abs(qty)

    new_qty = (p.quantity or 0) + qty
    if new_qty < 0:
        flash('Estoque insuficiente para saída.', 'warning')
        return redirect(url_for('products'))

    try:
        p.quantity = new_qty
        db.session.commit()
        flash('Movimentação registrado!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Falha ao registrar movimentação: {e}', 'warning')

    return redirect(url_for('products'))

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
    u = current_user()

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

    html_str = render_template(
        "result_pdf.html",
        patient_info=patient_info,
        diagnostic_text=(diagnostic_text or "—"),
        prescription_text=(prescription_text or "—"),
        doctor_name=doctor_display_name or (getattr(u, "name", None) or u.username),
    )

    pdf_io = BytesIO()

    # 1) Tenta WeasyPrint
    try:
        HTML(string=html_str, base_url=request.host_url).write_pdf(pdf_io)
        pdf_io.seek(0)
    except Exception as e:
        print("[PDF/gen] WeasyPrint error, fallback ReportLab:", e)
        # 2) Fallback ReportLab
        from reportlab.lib.pagesizes import A4  # type: ignore
        from reportlab.pdfgen import canvas    # type: ignore
        from reportlab.lib.units import mm     # type: ignore
        from reportlab.lib.utils import ImageReader  # type: ignore

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
                c.drawImage(img, width - target_w - 15*mm, height - target_h - 15*mm,
                            width=target_w, height=target_h, preserveAspectRatio=True, mask='auto')
            except Exception:
                pass

        c.setFont("Times-Bold", 16)
        c.drawCentredString(width / 2, height - 20 * mm, "Resultado da Análise - Ponza Health")

        c.setFont("Times-Roman", 11)
        y = height - 35 * mm
        for ln in patient_info.splitlines():
            c.drawString(20 * mm, y, ln); y -= 6 * mm

        y -= 4 * mm
        c.setFont("Times-Bold", 12); c.drawString(20 * mm, y, "Diagnóstico:"); y -= 7 * mm
        c.setFont("Times-Roman", 11)
        for ln in (diagnostic_text or "—").splitlines():
            c.drawString(22 * mm, y, ln); y -= 6 * mm
            if y < 25 * mm: c.showPage(); y = height - 20 * mm

        y -= 4 * mm
        c.setFont("Times-Bold", 12); c.drawString(20 * mm, y, "Prescrição:"); y -= 7 * mm
        c.setFont("Times-Roman", 11)
        for ln in (prescription_text or "—").splitlines():
            c.drawString(22 * mm, y, ln); y -= 6 * mm
            if y < 40 * mm: c.showPage(); y = height - 20 * mm

        c.setFont("Times-Roman", 11)
        c.line(60 * mm, 25 * mm, 150 * mm, 25 * mm)
        c.drawCentredString(105 * mm, 20 * mm, doctor_display_name or (getattr(u, "name", None) or u.username))

        c.showPage()
        c.save()
        pdf_io.seek(0)

    # Salva cópia no banco
    try:
        pdf_bytes = pdf_io.getvalue()
        display_name = f"Resultado_{(patient.name or 'Paciente').replace(' ', '_')}.pdf"
        _save_pdf_bytes_to_db(
            owner_user_id=u.id,
            patient_id=patient.id,
            consult_id=None,  # pode anexar depois se quiser
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

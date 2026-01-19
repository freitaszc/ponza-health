import os
import io
import re
import base64
import unicodedata
import mimetypes
import secrets
import stripe
import multiprocessing
import time
import hashlib
from flask_migrate import Migrate
from io import BytesIO
from functools import wraps
from contextlib import contextmanager
from typing import Any, Optional, Callable, cast
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone, date
from zoneinfo import ZoneInfo
from uuid import uuid4
import json
import tempfile
import requests
from urllib.parse import urljoin
from itsdangerous import URLSafeTimedSerializer, URLSafeSerializer, BadSignature, SignatureExpired
from flask_mail import Mail, Message
from dotenv import load_dotenv
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'), override=True)

from prescription import (
    analyze_pdf,
    send_pdf_whatsapp_template,
    send_pdf_whatsapp_patient,
    send_reminder_patient,
    send_quote_whatsapp,
    send_text,
)
from exam_analyzer.pdf_extractor import extract_exam_payload, extract_bioresonancia_payload
from exam_analyzer.ai import generate_ai_analysis, generate_bioresonancia_analysis
from flask import (
    Flask, Blueprint, render_template, request, redirect, url_for,
    session, flash, jsonify, abort, send_file, send_from_directory, g, current_app,
    get_flashed_messages, stream_with_context
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import select, func, or_
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import NullPool
from werkzeug.middleware.proxy_fix import ProxyFix
from apscheduler.schedulers.background import BackgroundScheduler #type:ignore

from models import (
    db, User, Patient, Doctor, Consult, PackageUsage,
    Supplier, Product, AgendaEvent, Quote, QuoteResponse,
    SecureFile, PdfFile, WaitlistItem, ScheduledEmail,
    StockMovement, quote_suppliers, PatientExamHistory,
    Cashbox, CashboxTransaction, PatientPayment,
)

# ------------------------------------------------------------------------------
# Inicialização / Config
# ------------------------------------------------------------------------------
app = Flask(__name__)

if os.getenv("RENDER"):
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)  # type: ignore

app.config["SEND_FILE_MAX_AGE_DEFAULT"] = int(os.getenv("SEND_FILE_MAX_AGE_DEFAULT", "3600"))

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), 'instance'))
os.makedirs(BASE_DIR, exist_ok=True)
STATIC_DIR = os.path.join(app.root_path, 'static')
os.makedirs(STATIC_DIR, exist_ok=True)
REACT_STATIC_DIR = os.path.join(STATIC_DIR, 'react')
UPLOAD_FOLDER = os.path.join(STATIC_DIR, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_hex(32)
app.config['SECRET_KEY'] = SECRET_KEY

ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}
DEFAULT_USER_IMAGE = "/static/images/user-icon.png"
DEFAULT_PATIENT_IMAGE = "/static/images/user-icon.png"

app.config["PUBLIC_BASE_URL"] = (
    os.getenv("PUBLIC_BASE_URL")
    or os.getenv("APP_BASE_URL")
    or os.getenv("PUBLIC_APP_URL")
)

smtp_username = os.getenv("SMTP_USERNAME")
default_sender_email = (os.getenv("EMAIL_FROM") or smtp_username or "")
default_sender_name = os.getenv("MAIL_SENDER_NAME", "Ponza Health")

app.config.update(
    MAIL_SERVER=os.getenv("SMTP_SERVER", "smtp.gmail.com"),
    MAIL_PORT=int(os.getenv("SMTP_PORT", 587)),
    MAIL_USE_TLS=(os.getenv("MAIL_USE_TLS", "true").strip().lower() == "true"),
    MAIL_USERNAME=smtp_username,
    MAIL_PASSWORD=os.getenv("SMTP_PASSWORD"),
    MAIL_DEFAULT_SENDER=(default_sender_name, default_sender_email),
)

mail = Mail(app)

def serve_react_index():
    index_path = os.path.join(REACT_STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return send_from_directory(REACT_STATIC_DIR, "index.html")
    return (
        "React build not found. Run npm install and npm run build in templates/frontend.",
        503,
    )


def allowed_file(filename: str) -> bool:
    return bool(filename) and '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


TRIAL_EXEMPT_ENDPOINTS = {
    "trial_locked",
    "api_trial_status",
    "subscribe_pay_mensal",
    "subscribe_pay_anual",
}


def _normalize_trial_expiration(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _plan_is_active(plan_status: Optional[str], plan_expires: Any) -> bool:
    if plan_status != "paid":
        return False
    if plan_expires is None:
        return True
    now = datetime.utcnow()
    if isinstance(plan_expires, datetime):
        return plan_expires >= now
    if isinstance(plan_expires, date):
        return plan_expires >= now.date()
    return False


def _is_admin_user(user: User) -> bool:
    username = (getattr(user, "username", "") or "").strip().lower()
    return username == "admin"

def _admin_guard_response() -> Optional[Any]:
    user = current_user()
    if _is_admin_user(user):
        return None
    if _request_wants_json():
        return jsonify({"success": False, "error": "forbidden"}), 403
    return redirect(url_for('index'))


def _build_trial_status(user: User) -> dict[str, Any]:
    if _is_admin_user(user):
        return {
            "plan_active": True,
            "plan_status": "admin",
            "plan_expires": None,
            "trial_active": False,
            "trial_expired": False,
            "trial_expiration": None,
            "plans": {
                "monthly": url_for("subscribe_pay_mensal"),
                "yearly": url_for("subscribe_pay_anual"),
            },
        }
    now_date = datetime.utcnow().date()
    trial_expiration = _normalize_trial_expiration(getattr(user, "trial_expiration", None))
    plan_status = getattr(user, "plan_status", None)
    plan_expires = getattr(user, "plan_expiration", None)
    plan_active = _plan_is_active(plan_status, plan_expires)
    trial_active = bool(trial_expiration and trial_expiration >= now_date)
    trial_expired = bool(trial_expiration and trial_expiration < now_date)
    return {
        "plan_active": plan_active,
        "plan_status": plan_status or "",
        "plan_expires": plan_expires.isoformat() if isinstance(plan_expires, (date, datetime)) else None,
        "trial_active": trial_active,
        "trial_expired": trial_expired,
        "trial_expiration": trial_expiration.isoformat() if trial_expiration else None,
        "plans": {
            "monthly": url_for("subscribe_pay_mensal"),
            "yearly": url_for("subscribe_pay_anual"),
        },
    }

def _serialize_admin_user(user: User) -> dict[str, Any]:
    def _iso(value: Any) -> Optional[str]:
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return None

    pkg = PackageUsage.query.filter_by(user_id=user.id).first()
    pkg_total = _coerce_int(getattr(pkg, "total", DEFAULT_FREE_ANALYSIS_ALLOWANCE), default=DEFAULT_FREE_ANALYSIS_ALLOWANCE)
    pkg_used = _coerce_int(getattr(pkg, "used", 0))
    pkg_remaining = max(pkg_total - pkg_used, 0)

    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "plan": (user.plan or "").strip().lower(),
        "plan_status": user.plan_status or "",
        "plan_expires": _iso(user.plan_expiration),
        "trial_expires": _iso(user.trial_expiration),
        "created_at": _iso(user.created_at),
        "package_total": pkg_total,
        "package_used": pkg_used,
        "package_remaining": pkg_remaining,
    }

def _extend_user_subscription(user: User, plan: str) -> None:
    normalized = (plan or "").strip().lower()
    if normalized not in {"monthly", "yearly"}:
        raise ValueError("Plano inválido.")

    previous_plan = (user.plan or "").strip().lower()
    now = datetime.utcnow()
    base_expiration = user.plan_expiration
    if isinstance(base_expiration, date) and not isinstance(base_expiration, datetime):
        base_expiration = datetime.combine(base_expiration, datetime.min.time())
    if not base_expiration or base_expiration < now:
        base_expiration = now

    delta = timedelta(days=365 if normalized == "yearly" else 30)
    user.plan = normalized
    user.plan_status = "paid"
    user.trial_expiration = None
    user.plan_expiration = base_expiration + delta

    if _apply_plan_allowance(user, normalized, previous_plan=previous_plan):
        db.session.add(user)

def _delete_user_account(user: User) -> None:
    user_id = user.id

    patient_ids = [row[0] for row in db.session.query(Patient.id).filter(Patient.user_id == user_id).all()]
    consult_ids = []
    if patient_ids:
        consult_ids = [
            row[0]
            for row in db.session.query(Consult.id).filter(Consult.patient_id.in_(patient_ids)).all()
        ]

    pdf_filters = []
    if patient_ids:
        pdf_filters.append(PdfFile.patient_id.in_(patient_ids))
    if consult_ids:
        pdf_filters.append(PdfFile.consult_id.in_(consult_ids))
    if pdf_filters:
        db.session.query(PdfFile).filter(or_(*pdf_filters)).delete(synchronize_session=False)

    quote_ids = [row[0] for row in db.session.query(Quote.id).filter(Quote.user_id == user_id).all()]
    if quote_ids:
        db.session.execute(quote_suppliers.delete().where(quote_suppliers.c.quote_id.in_(quote_ids)))
        db.session.query(QuoteResponse).filter(QuoteResponse.quote_id.in_(quote_ids)).delete(
            synchronize_session=False
        )
        db.session.query(Quote).filter(Quote.id.in_(quote_ids)).delete(synchronize_session=False)

    supplier_ids = [row[0] for row in db.session.query(Supplier.id).filter(Supplier.user_id == user_id).all()]
    if supplier_ids:
        db.session.execute(quote_suppliers.delete().where(quote_suppliers.c.supplier_id.in_(supplier_ids)))
        db.session.query(QuoteResponse).filter(QuoteResponse.supplier_id.in_(supplier_ids)).delete(
            synchronize_session=False
        )
        db.session.query(Supplier).filter(Supplier.id.in_(supplier_ids)).delete(synchronize_session=False)

    product_ids = [row[0] for row in db.session.query(Product.id).filter(Product.user_id == user_id).all()]
    if product_ids:
        db.session.query(StockMovement).filter(StockMovement.product_id.in_(product_ids)).delete(
            synchronize_session=False
        )
        db.session.query(Product).filter(Product.id.in_(product_ids)).delete(synchronize_session=False)

    db.session.query(AgendaEvent).filter(AgendaEvent.user_id == user_id).delete(synchronize_session=False)
    db.session.query(PackageUsage).filter(PackageUsage.user_id == user_id).delete(synchronize_session=False)
    db.session.query(WaitlistItem).filter(WaitlistItem.user_id == user_id).delete(synchronize_session=False)
    db.session.query(ScheduledEmail).filter(ScheduledEmail.user_id == user_id).delete(synchronize_session=False)

    doctor_ids = [row[0] for row in db.session.query(Doctor.id).filter(Doctor.user_id == user_id).all()]
    if doctor_ids:
        db.session.query(Doctor).filter(Doctor.id.in_(doctor_ids)).delete(synchronize_session=False)

    if consult_ids:
        db.session.query(Consult).filter(Consult.id.in_(consult_ids)).delete(synchronize_session=False)
    if patient_ids:
        db.session.query(Patient).filter(Patient.id.in_(patient_ids)).delete(synchronize_session=False)

    secure_file_ids = [
        row[0] for row in db.session.query(SecureFile.id).filter(SecureFile.user_id == user_id).all()
    ]
    if secure_file_ids:
        db.session.query(PdfFile).filter(PdfFile.secure_file_id.in_(secure_file_ids)).delete(
            synchronize_session=False
        )
        db.session.query(SecureFile).filter(SecureFile.id.in_(secure_file_ids)).delete(
            synchronize_session=False
        )

    db.session.delete(user)

DEFAULT_FREE_ANALYSIS_ALLOWANCE = 25
ANNUAL_PLAN_BONUS_ANALYSES = 30

GMAIL_CLIENT_ID = os.getenv("GMAIL_CLIENT_ID")
GMAIL_CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET") or os.getenv("CLIENTE_SECRET")
GMAIL_REFRESH_TOKEN = os.getenv("GMAIL_REFRESH_TOKEN")
GMAIL_TOKEN_URI = os.getenv("TOKEN_URI") or "https://oauth2.googleapis.com/token"
GMAIL_API_USER = os.getenv("EMAIL_FROM") or os.getenv("SMTP_USERNAME")
GMAIL_API_TIMEOUT = int(os.getenv("GMAIL_API_TIMEOUT", "30"))
GMAIL_API_ENABLED = all([GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN])


def _gmail_get_access_token() -> str:
    if not GMAIL_API_ENABLED:
        raise RuntimeError("Gmail API não configurada.")

    data = {
        "client_id": GMAIL_CLIENT_ID,
        "client_secret": GMAIL_CLIENT_SECRET,
        "refresh_token": GMAIL_REFRESH_TOKEN,
        "grant_type": "refresh_token",
    }

    response = requests.post(GMAIL_TOKEN_URI, data=data, timeout=GMAIL_API_TIMEOUT)
    if response.status_code >= 400:
        raise RuntimeError(
            f"Falha ao obter token do Gmail: status {response.status_code} — {response.text[:200]}"
        )

    token_data = response.json()
    token = token_data.get("access_token")
    if not token:
        raise RuntimeError("Resposta do Gmail sem access_token.")
    return str(token)


def _gmail_build_message(
    *,
    subject: str,
    recipients: list[str],
    sender: str,
    html: Optional[str],
    body: Optional[str],
    reply_to: Optional[str],
    inline_images: Optional[list[dict[str, str]]],
) -> bytes:
    msg_root = MIMEMultipart("related")
    msg_root["Subject"] = subject
    msg_root["From"] = sender
    msg_root["To"] = ", ".join(recipients)
    if reply_to:
        msg_root["Reply-To"] = reply_to

    alternative = MIMEMultipart("alternative")
    if body and html:
        alternative.attach(MIMEText(body, "plain", "utf-8"))
        alternative.attach(MIMEText(html, "html", "utf-8"))
    elif html:
        alternative.attach(MIMEText(html, "html", "utf-8"))
    else:
        alternative.attach(MIMEText(body or "", "plain", "utf-8"))
    msg_root.attach(alternative)

    for image in inline_images or []:
        path = image.get("path")
        if not path:
            continue
        try:
            with app.open_resource(path) as fp:
                img_data = fp.read()
        except FileNotFoundError:
            continue

        mime_type = mimetypes.guess_type(path)[0] or "image/png"
        maintype, subtype = mime_type.split("/", 1)
        if maintype != "image":
            maintype, subtype = "image", "png"

        img_part = MIMEImage(img_data, _subtype=subtype)
        cid = image.get("cid")
        if cid:
            img_part.add_header("Content-ID", f"<{cid}>")
        filename = image.get("filename") or os.path.basename(path)
        img_part.add_header("Content-Disposition", "inline", filename=filename)
        msg_root.attach(img_part)

    return msg_root.as_bytes()


def _send_email_via_gmail_api(
    *,
    subject: str,
    recipients: list[str],
    sender: str,
    html: Optional[str],
    body: Optional[str],
    reply_to: Optional[str],
    inline_images: Optional[list[dict[str, str]]],
) -> None:
    if not recipients:
        return

    access_token = _gmail_get_access_token()
    raw_bytes = _gmail_build_message(
        subject=subject,
        recipients=recipients,
        sender=sender,
        html=html,
        body=body,
        reply_to=reply_to,
        inline_images=inline_images,
    )
    encoded_message = base64.urlsafe_b64encode(raw_bytes).decode("utf-8")

    response = requests.post(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json={"raw": encoded_message},
        timeout=GMAIL_API_TIMEOUT,
    )

    if response.status_code >= 400:
        raise RuntimeError(
            f"Erro ao enviar e-mail via Gmail API: status {response.status_code} — {response.text[:200]}"
        )


def send_email(subject, recipients, html=None, body=None, sender=None, reply_to=None, inline_images=None):
    """
    Envia e-mail com suporte a imagens inline via CID.
    inline_images deve ser uma lista de dicts: [{"filename": "logo.png", "path": "static/images/7.png", "cid": "logo"}]
    """
    recipients_list = list(recipients or [])

    resolved_sender = sender or GMAIL_API_USER or app.config.get("MAIL_DEFAULT_SENDER")
    if isinstance(resolved_sender, tuple):
        resolved_sender = resolved_sender[1]
    if resolved_sender is None:
        resolved_sender = app.config.get("MAIL_DEFAULT_SENDER")
        if isinstance(resolved_sender, tuple):
            resolved_sender = resolved_sender[1]
    resolved_sender = str(resolved_sender)

    if GMAIL_API_ENABLED:
        try:
            _send_email_via_gmail_api(
                subject=subject,
                recipients=recipients_list,
                sender=resolved_sender,
                html=html,
                body=body,
                reply_to=reply_to,
                inline_images=inline_images,
            )
            return
        except Exception as exc:
            current_app.logger.exception("Erro ao enviar e-mail via Gmail API, tentando SMTP: %s", exc)

    msg = Message(
        subject=subject,
        recipients=recipients_list,
        sender=resolved_sender,
        reply_to=reply_to
    )
    if html:
        msg.html = html
    if body:
        msg.body = body

    if inline_images:
        for img in inline_images:
            try:
                with app.open_resource(img["path"]) as fp:
                    msg.attach(
                        img["filename"],
                        "image/png",
                        fp.read(),
                        "inline",
                        headers={"Content-ID": f"<{img['cid']}>"}
                    )
            except FileNotFoundError:
                current_app.logger.warning("Imagem inline não encontrada: %s", img.get("path"))

    mail.send(msg)

def _coerce_int(value: Any, *, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _env_positive_int(keys: list[str], *, default: int) -> int:
    """Retorna o primeiro valor inteiro positivo encontrado nas variáveis informadas."""
    for key in keys:
        value = _coerce_int(os.getenv(key), default=0)
        if value > 0:
            return value
    return default


def _ensure_package_usage(user: User, *, base_total: Optional[int] = None) -> tuple[PackageUsage, bool]:
    """Garantir que o usuário possua registro de pacote com o mínimo configurado."""
    baseline = base_total if base_total is not None else DEFAULT_FREE_ANALYSIS_ALLOWANCE
    pkg = PackageUsage.query.filter_by(user_id=user.id).first()
    changed = False

    if not pkg:
        pkg = PackageUsage(user_id=user.id, total=baseline, used=0)
        db.session.add(pkg)
        changed = True
    else:
        if pkg.used is None:
            pkg.used = 0
            changed = True
        if pkg.total is None:
            pkg.total = baseline
            changed = True

    current_total = _coerce_int(getattr(pkg, "total", baseline), default=baseline)
    if current_total < baseline:
        pkg.total = baseline
        changed = True

    return pkg, changed


def _analysis_package_status(user: User) -> tuple[PackageUsage, int]:
    """Retorna o pacote do usuário e quantas análises restam."""
    pkg, changed = _ensure_package_usage(user, base_total=DEFAULT_FREE_ANALYSIS_ALLOWANCE)
    if changed:
        db.session.commit()
    used = _coerce_int(getattr(pkg, "used", 0))
    total = _coerce_int(getattr(pkg, "total", DEFAULT_FREE_ANALYSIS_ALLOWANCE), default=DEFAULT_FREE_ANALYSIS_ALLOWANCE)
    remaining = max(total - used, 0)
    return pkg, remaining


def _consume_analysis_slot(pkg: PackageUsage) -> None:
    """Incrementa o uso de análises após uma execução bem-sucedida."""
    pkg.used = _coerce_int(getattr(pkg, "used", 0)) + 1
    db.session.add(pkg)
    db.session.commit()


def _apply_plan_allowance(user: User, plan: str, previous_plan: Optional[str] = None) -> bool:
    """Atualiza o pacote do usuário de acordo com o plano atual."""
    normalized = (plan or "").strip().lower()
    prev = (previous_plan or (user.plan or "")).strip().lower()
    pkg, changed = _ensure_package_usage(user, base_total=DEFAULT_FREE_ANALYSIS_ALLOWANCE)

    if normalized == "yearly" and prev != "yearly":
        pkg.total = _coerce_int(pkg.total) + ANNUAL_PLAN_BONUS_ANALYSES
        changed = True

    return changed


def wants_json_response() -> bool:
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return True
    accept = request.accept_mimetypes
    return accept['application/json'] >= accept['text/html']


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

# Configura o SQLAlchemy para conectar ao Supabase. Mantemos o pool pequeno
# para não ultrapassar o limite do PgBouncer do Supabase, evitando o erro
# "MaxClientsInSessionMode".
db_pool_size = max(_coerce_int(os.getenv("DB_POOL_SIZE"), default=3), 1)
db_max_overflow = max(_coerce_int(os.getenv("DB_MAX_OVERFLOW"), default=0), 0)
pool_timeout = max(_coerce_int(os.getenv("DB_POOL_TIMEOUT"), default=30), 5)
worker_processes = max(_env_positive_int(["WEB_CONCURRENCY", "GUNICORN_WORKERS", "WORKERS"], default=1), 1)
supabase_max_clients = max(_coerce_int(os.getenv("SUPABASE_MAX_CLIENTS"), default=worker_processes), 1)
reserved_clients = max(_coerce_int(os.getenv("SUPABASE_RESERVED_CONNECTIONS"), default=0), 0)
available_db_clients = max(1, supabase_max_clients - reserved_clients)
force_null_pool = (
    os.getenv("DB_FORCE_NULLPOOL", "").strip().lower()
    in {"1", "true", "yes", "on"}
)

per_worker_budget = max(1, supabase_max_clients // worker_processes)
effective_pool_size = min(db_pool_size, per_worker_budget)
effective_max_overflow = min(db_max_overflow, max(0, per_worker_budget - effective_pool_size))
use_null_pool = force_null_pool or supabase_max_clients <= worker_processes

if reserved_clients:
    print(
        f"[DB] Reservando {reserved_clients} conexão(ões) para outros serviços; "
        f"{available_db_clients} ficarão disponíveis para este app."
    )

if worker_processes > supabase_max_clients:
    print(
        f"[DB] ATENCAO: existem {worker_processes} workers configurados, "
        f"mas o Supabase permite apenas {supabase_max_clients} conexões simultâneas. "
        "Considere reduzir WEB_CONCURRENCY ou elevar SUPABASE_MAX_CLIENTS."
    )

engine_options: dict[str, Any] = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
}

if use_null_pool:
    reason = "forçado por DB_FORCE_NULLPOOL" if force_null_pool else "limite total <= workers"
    print(
        f"[DB] Habilitando NullPool ({reason}); conexões serão abertas/fechadas sob demanda."
    )
    engine_options["poolclass"] = NullPool
else:
    if effective_pool_size < db_pool_size:
        print(
            f"[DB] Ajustando pool_size solicitado ({db_pool_size}) para {effective_pool_size} "
            f"para respeitar o limite total de {supabase_max_clients} conexões."
        )

    if effective_max_overflow < db_max_overflow:
        print(
            f"[DB] Ajustando max_overflow solicitado ({db_max_overflow}) para {effective_max_overflow} "
            f"para respeitar o limite total de {supabase_max_clients} conexões."
        )

    engine_options.update({
        "pool_timeout": pool_timeout,
        "pool_size": effective_pool_size,
        "max_overflow": effective_max_overflow,
    })

app.config.update(
    SQLALCHEMY_DATABASE_URI=DATABASE_URL,
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SQLALCHEMY_ENGINE_OPTIONS=engine_options,
)

db.init_app(app)
migrate = Migrate(app, db)

try:
    _db_connection_semaphore = multiprocessing.BoundedSemaphore(available_db_clients)
    print(f"[DB] Limite global de {available_db_clients} conexões simultâneas configurado.")
except Exception as exc:
    _db_connection_semaphore = None
    print("[DB] ⚠️ Semáforo global de conexões indisponível:", exc)


def _acquire_db_slot() -> bool:
    if _db_connection_semaphore is None:
        return False
    _db_connection_semaphore.acquire()
    return True


def _release_db_slot() -> None:
    if _db_connection_semaphore is None:
        return
    _db_connection_semaphore.release()


@contextmanager
def db_slot_guard():
    acquired = _acquire_db_slot()
    try:
        yield
    finally:
        if acquired:
            _release_db_slot()

# ------------------------------------------------------------------------------
# Conexão e verificação
# ------------------------------------------------------------------------------
with db_slot_guard():
    with app.app_context():
        try:
            from sqlalchemy import inspect
            insp = inspect(db.engine)
            print("[DB] ✅ Conectado ao Supabase PostgreSQL com sucesso!")
            print(f"[DB] Tabelas detectadas: {insp.get_table_names()}")
        except Exception as e:
            print("[DB] ❌ Erro ao conectar ao Supabase:", e)


@app.before_request
def _before_request_acquire_db_slot():
    g._db_slot_acquired = _acquire_db_slot()


@app.teardown_request
def _teardown_request_release_db_slot(exc):
    acquired = g.pop("_db_slot_acquired", False)
    if acquired:
        _release_db_slot()


@app.teardown_appcontext
def _shutdown_session(exc: Optional[BaseException] = None):
    db.session.remove()

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


def _resolve_public_logo_url(filename: str) -> str:
    public_base = current_app.config.get("PUBLIC_BASE_URL")
    if public_base:
        base = public_base.rstrip("/")
        return f"{base}/static/images/{filename}"
    return url_for("static", filename=f"images/{filename}", _external=True)


def _public_base_url() -> Optional[str]:
    return (
        current_app.config.get("PUBLIC_BASE_URL")
        or current_app.config.get("APP_BASE_URL")
        or os.getenv("PUBLIC_APP_URL")
        or os.getenv("APP_BASE_URL")
    )


def _external_endpoint_url(endpoint: str, **values: Any) -> str:
    relative = url_for(endpoint, _external=False, **values)
    base_url = _public_base_url()
    if base_url:
        return urljoin(base_url.rstrip("/") + "/", relative.lstrip("/"))
    return url_for(endpoint, _external=True, **values)


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
        payload = request.get_json(silent=True)
        if not payload:
            payload = request.form
        email = (payload.get("email") or "").strip().lower()
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

        if _request_wants_json():
            return jsonify({"success": True})
        flash("Se este e-mail existir, enviaremos um link de recuperação.", "info")
        return redirect(url_for("pw_forgot"))

    return serve_react_index()

# ------------------------------------------------------------------------------
# Reset de senha
# ------------------------------------------------------------------------------
@app.route("/reset_password/<token>", methods=["GET", "POST"])
def pw_reset(token):
    email = verify_reset_token(token)
    if not email:
        if _request_wants_json():
            return jsonify({"error": "invalid_token"}), 400
        flash("Link inválido ou expirado.", "danger")
        return redirect(url_for("pw_forgot"))

    if request.method == "POST":
        payload = request.get_json(silent=True)
        if not payload:
            payload = request.form
        password = (payload.get("password") or "").strip()
        confirm = (payload.get("confirm") or "").strip()

        if not password or len(password) < 6:
            if _request_wants_json():
                return jsonify({"error": "password_too_short"}), 400
            flash("Informe uma nova senha com pelo menos 6 caracteres.", "danger")
            return redirect(request.url)
        if password != confirm:
            if _request_wants_json():
                return jsonify({"error": "password_mismatch"}), 400
            flash("As senhas não coincidem.", "danger")
            return redirect(request.url)

        user = User.query.filter(func.lower(User.email) == email.lower()).first()
        if not user:
            if _request_wants_json():
                return jsonify({"error": "user_not_found"}), 404
            flash("Usuário não encontrado.", "danger")
            return redirect(url_for("login"))

        user.set_password(password)
        db.session.commit()

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

        if _request_wants_json():
            return jsonify({"success": True})
        flash("Senha alterada com sucesso. Faça login.", "success")
        return redirect(url_for("login"))

    return serve_react_index()

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
    if not uid:
        return None
    try:
        return User.query.get(uid)
    except OperationalError as oe:
        # DB is unavailable (connection refused / network issue). Return None so
        # login_required and other callers can handle an unauthenticated user
        # instead of raising a 500. Log the error for diagnostics.
        try:
            current_app.logger.error("Database OperationalError when fetching user %s: %s", uid, oe)
        except Exception:
            # current_app may not be available in some edge cases; swallow logging errors.
            pass
        return None
    except Exception as e:
        # Fallback: log unexpected exceptions and return None to avoid crashing requests
        try:
            current_app.logger.exception("Unexpected error when fetching logged user %s: %s", uid, e)
        except Exception:
            pass
        return None

def _request_wants_json() -> bool:
    """Detecta se a requisição espera uma resposta JSON (fetch/API)."""
    if request.is_json:
        return True
    content_type = (request.headers.get('Content-Type') or '').lower()
    if 'application/json' in content_type:
        return True
    if request.path.startswith('/api/'):
        return True
    accept = (request.headers.get('Accept') or '').lower()
    if 'application/json' in accept and 'text/html' not in accept:
        return True
    if (request.headers.get('X-Requested-With') or '').lower() == 'xmlhttprequest':
        return True
    return False


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
        if _is_admin_user(u):
            return f(*args, **kwargs)

        trial_expiration = _normalize_trial_expiration(getattr(u, "trial_expiration", None))
        plan_status = getattr(u, "plan_status", None)
        plan_expires = getattr(u, "plan_expiration", None)

        # Paid users: allow if still valid
        if _plan_is_active(plan_status, plan_expires):
            return f(*args, **kwargs)

        # Trial users: compare dates only
        now_date = datetime.utcnow().date()
        if trial_expiration and trial_expiration >= now_date:
            return f(*args, **kwargs)

        # Trial expirou → bloquear acesso e liberar apenas pagamento
        if trial_expiration:
            message = "Seu período de teste de 14 dias expirou. Faça a assinatura para continuar usando o sistema."

            if request.endpoint in TRIAL_EXEMPT_ENDPOINTS:
                return f(*args, **kwargs)

            if _request_wants_json():
                return jsonify({
                    "error": "trial_expired",
                    "message": message,
                    "plans": {
                        "monthly": url_for('subscribe_pay_mensal'),
                        "yearly": url_for('subscribe_pay_anual'),
                    },
                }), 402

            return redirect(url_for('trial_locked'))

        # fallback legacy: sem trial → direciona para planos
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

def _register_validation_error(username: str, email: str, password: str, confirm: str) -> Optional[str]:
    if len(password) < 8:
        return "A senha deve ter pelo menos 8 caracteres."
    if not re.search(r"[A-Z]", password):
        return "A senha deve conter pelo menos uma letra maiuscula."
    if not re.search(r"\d", password):
        return "A senha deve conter pelo menos um número."
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>_+=\-]", password):
        return "A senha deve conter pelo menos um caractere especial."
    if password != confirm:
        return "As senhas não coincidem."
    if not username:
        return "Informe um nome de usuario."
    if User.query.filter_by(username=username).first():
        return "Este nome de usuario ja esta em uso."
    existing_email = User.query.filter(func.lower(User.email) == email.lower()).first()
    if existing_email:
        return "Este e-mail ja esta cadastrado."
    return None

def _process_register(payload: dict[str, Any]) -> tuple[bool, str]:
    username = (payload.get("username") or "").strip()
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    confirm = payload.get("confirm") or ""
    plan = (payload.get("plan") or "").strip()

    error = _register_validation_error(username, email, password, confirm)
    if error:
        return False, error

    s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    token = s.dumps(
        {
            "username": username,
            "email": email,
            "password_hash": generate_password_hash(password),
            "plan": plan,
        },
        salt="email-confirm",
    )
    confirm_url = url_for("auth.verify_email", token=token, _external=True)
    
    public_base = current_app.config.get("PUBLIC_BASE_URL", "").rstrip("/")
    logo_url = f"{public_base}/static/images/2.png" if public_base else url_for("static", filename="images/2.png", _external=True)

    html = render_template(
        "emails/verify_account.html",
        username=username,
        confirm_url=confirm_url,
        current_year=datetime.utcnow().year,
        logo_url=logo_url,
    )
    
    # Versão texto puro para melhor entregabilidade
    plain_text = f"""Olá {username},

Obrigado por se cadastrar na Ponza Health!

Para ativar sua conta, acesse o link abaixo:
{confirm_url}

Se você não criou uma conta conosco, basta ignorar este e-mail.

Atenciosamente,
Equipe Ponza Health
WhatsApp: +55 33 98461-3689
"""
    
    try:
        send_email(
            subject="Confirme sua conta - Ponza Health",
            recipients=[email],
            html=html,
            body=plain_text,
            reply_to="ponzahealth@gmail.com",
        )
    except Exception as exc:
        current_app.logger.exception("Falha ao enviar e-mail de verificação: %s", exc)
        return False, "Não foi possível enviar o e-mail de verificação. Verifique se o e-mail está correto e tente novamente."

    message = (
        "Conta criada com sucesso! Enviamos um link de confirmacao para "
        f"{email}. Conclua a verificacao e depois faca login."
    )
    return True, message

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


@app.after_request
def add_static_cache_headers(response):
    path = request.path or ""
    if path.startswith("/static/react/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response
    if path.startswith("/static/"):
        response.headers.setdefault("Cache-Control", "public, max-age=86400")
    return response

auth_bp = Blueprint('auth', __name__, template_folder='templates/auth')

# ------------------------------------------------------------------------------
# Cadastro com verificação de e-mail e suporte a plano (trial / mensal / anual)
# ------------------------------------------------------------------------------
@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        payload = request.get_json(silent=True)
        if not payload:
            payload = request.form

        ok, message = _process_register(payload)
        if _request_wants_json():
            if ok:
                return jsonify({
                    "success": True,
                    "message": message,
                })
            return jsonify({"success": False, "error": message}), 400

        if ok:
            flash(message, "login_success")
            return redirect(url_for("login"))
        flash(message, "login_error")
        return redirect(url_for("auth.register"))

    return serve_react_index()


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
    normalized_plan = plan if plan in {'monthly', 'yearly'} else 'trial'

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
        plan=normalized_plan,
        plan_status='pending_payment' if normalized_plan in {'monthly', 'yearly'} else 'trial',
        trial_expiration=None if normalized_plan in {'monthly', 'yearly'} else now + timedelta(days=14),
        plan_expiration=None
    )
    db.session.add(new_user)
    db.session.flush()
    _ensure_package_usage(new_user, base_total=DEFAULT_FREE_ANALYSIS_ALLOWANCE)
    db.session.commit()

    # Agendar e-mails do trial apenas se não houver plano
    if normalized_plan == 'trial':
        try:
            schedule_trial_emails(new_user.id)
        except Exception:
            current_app.logger.exception("Falha ao agendar e-mails de trial")

    # Se o usuário escolheu um plano (mensal/anual), envia direto pro Stripe
    if normalized_plan in ['monthly', 'yearly']:
        stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

        base_url = (_public_base_url() or request.host_url).rstrip('/')
        price_amount = 838.80 if normalized_plan == 'yearly' else 79.90
        interval = 'year' if normalized_plan == 'yearly' else 'month'
        plan_name = f"Plano {'Anual' if normalized_plan == 'yearly' else 'Mensal'} Ponza Health"

        payment_methods = ['card', 'boleto']

        def _create_checkout(methods):
            return stripe.checkout.Session.create(
                payment_method_types=methods,
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
                metadata={'user_id': str(new_user.id), 'plan': normalized_plan},
                success_url=f"{base_url}/subscription/success?session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{base_url}/planos"
            )

        try:
            try:
                session = _create_checkout(payment_methods)
            except stripe.error.InvalidRequestError as exc:  # type: ignore[attr-defined]
                param = (getattr(exc, "param", "") or "").lower()
                message = str(exc).lower()
                if "payment_method_types" in param or "payment_method_types" in message or "boleto" in message:
                    current_app.logger.warning(
                        "[Stripe] Boleto indisponivel para assinatura. Usando cartao. (%s)",
                        exc,
                    )
                    session = _create_checkout(['card'])
                else:
                    raise
            # Redireciona para o checkout Stripe (nova aba / link)
            url = session.url or url_for("payments")
            return redirect(url, code=303)
        except Exception as e:
            current_app.logger.error(f"[Stripe] Erro ao criar sessão de checkout: {e}")
            flash("Erro ao iniciar pagamento. Tente novamente mais tarde.", "danger")
            return redirect(url_for('prices'))

    # Caso padrão: usuário sem plano → trial gratuito
    # Redireciona para login com parâmetro para mostrar mensagem de sucesso
    return redirect(url_for('login', confirmed='true'))


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
    public_base = current_app.config.get("PUBLIC_BASE_URL", "").rstrip("/")
    logo_url = f"{public_base}/static/images/2.png" if public_base else url_for("static", filename="images/2.png", _external=True)
    
    for e in emails:
        user = User.query.get(e.user_id)
        if not user:
            continue

        html = render_template(f'emails/{e.template}.html', user=user, logo_url=logo_url)
        
        # Texto puro para melhor entregabilidade
        plain_text = f"""Olá {user.username},

Este é um lembrete sobre seu período de teste na Ponza Health.

Acesse sua conta em: {public_base or 'https://ponzahealth.com.br'}

Atenciosamente,
Equipe Ponza Health
WhatsApp: +55 33 98461-3689
"""
        
        send_email(
            subject='Ponza Health - Lembrete do período de teste',
            recipients=[user.email],
            html=html,
            body=plain_text,
            reply_to="ponzahealth@gmail.com",
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
    return serve_react_index()

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

def _login_with_credentials(login_input: str, pwd: str) -> tuple[bool, str]:
    if '@' in login_input:
        user = User.query.filter(func.lower(User.email) == login_input.lower()).first()
    else:
        user = User.query.filter(User.username == login_input).first()

    stored_hash = getattr(user, 'password_hash', None) if user else None
    if not user or not stored_hash or not check_password_hash(stored_hash, pwd):
        return False, 'Usuario ou senha inválidos.'

    session['user_id'] = user.id
    session['username'] = user.username
    return True, ""

@app.route('/api/login', methods=['POST'])
def api_login():
    payload = request.get_json(silent=True) or {}
    login_input = (payload.get('login') or '').strip()
    pwd = payload.get('password') or ''
    ok, error = _login_with_credentials(login_input, pwd)
    if not ok:
        return jsonify({"success": False, "error": error}), 401
    return jsonify({"success": True, "redirect": url_for("index")})

@app.route('/api/register', methods=['POST'])
def api_register():
    payload = request.get_json(silent=True) or {}
    ok, message = _process_register(payload)
    if ok:
        return jsonify({
            "success": True,
            "message": message,
            "redirect": url_for("login"),
        })
    return jsonify({"success": False, "error": message}), 400

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        payload = request.get_json(silent=True)
        if not payload:
            payload = request.form
        login_input = (payload.get('login') or '').strip()
        pwd = payload.get('password') or ''
        ok, error = _login_with_credentials(login_input, pwd)
        if not ok:
            if _request_wants_json():
                return jsonify({"success": False, "error": error}), 401
            flash('Usuário ou senha inválidos.', 'login_error')
            return redirect(url_for('login'))

        if _request_wants_json():
            return jsonify({"success": True, "redirect": url_for("index")})
        return redirect(url_for('index'))

    return serve_react_index()

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/trial_locked')
@login_required
def trial_locked():
    return serve_react_index()

@app.route('/api/trial_status')
@login_required
def api_trial_status():
    u = current_user()
    return jsonify(_build_trial_status(u))

@app.route('/privacy_policy')
def privacy_policy():
    return serve_react_index()

@app.route('/privacy')
def privacy_redirect():
    return redirect(url_for('privacy_policy'))

@app.route('/termos')
def terms():
    return serve_react_index()

@app.route('/terms')
def terms_redirect():
    return redirect(url_for('terms'))

@app.route('/planos')
def prices():
    return serve_react_index()

@app.route('/about')
def about():
    return serve_react_index()

@app.route('/centraldeajuda')
def help():
    return serve_react_index()

@app.route('/ajuda')
def ajuda():
    return serve_react_index()

@app.route('/quem-somos')
def quem_somos():
    return serve_react_index()

@app.route('/cadastro')
def cadastro():
    return serve_react_index()

# ------------------------------------------------------------------------------
# Dashboard
# ------------------------------------------------------------------------------
def _build_dashboard_payload(u: User) -> dict[str, Any]:
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

    pkg, pkg_changed = _ensure_package_usage(u, base_total=DEFAULT_FREE_ANALYSIS_ALLOWANCE)
    if pkg_changed:
        db.session.commit()
    used = _coerce_int(getattr(pkg, "used", 0))
    total = _coerce_int(getattr(pkg, "total", DEFAULT_FREE_ANALYSIS_ALLOWANCE))
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
    consults_week_series = []  # [{d:'dd/mm', primeira:int, retorno:int}]
    for i in range(7):
        day = start_7 + timedelta(days=i)
        day_start = datetime.combine(day, datetime.min.time())
        day_end = datetime.combine(day, datetime.max.time())
        qday = (
            AgendaEvent.query
            .filter(
                AgendaEvent.user_id == u.id,
                AgendaEvent.start >= day_start,
                AgendaEvent.end <= day_end
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
    insurance_convenio_30 = sum(1 for e in events_30 if (e.billing or "").lower() == "convenio")

    # PDFs analisados (últimos 7 dias)
    pdf_counts = {}
    for i in range(7):
        day = start_7 + timedelta(days=i)
        pdf_counts[day] = 0
    try:
        pdfs = (
            PdfFile.query
            .join(SecureFile, PdfFile.secure_file_id == SecureFile.id)
            .filter(
                SecureFile.user_id == u.id,
                PdfFile.uploaded_at >= datetime.combine(start_7, datetime.min.time()),
            )
            .all()
        )
        for pdf in pdfs:
            if not pdf.uploaded_at:
                continue
            day = pdf.uploaded_at.date()
            if day in pdf_counts:
                pdf_counts[day] += 1
    except Exception as e:
        print("[INDEX] pdf analytics error:", e)
    pdf_analyses_last7 = [
        {"d": day.strftime("%d/%m"), "count": int(pdf_counts.get(day, 0))}
        for day in sorted(pdf_counts.keys())
    ]

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

    return {
        "username": getattr(u, "name", None) or getattr(u, "username", None) or "",
        "total_patients": total_patients,
        "total_consults": total_consults,
        "used": used,
        "remaining": remaining,
        "package_used": used,
        "package_limit": total,
        "package_total": total,
        "consults_week_series": consults_week_series,
        "patients_new_30": patients_new_30,
        "patients_return_30": patients_return_30,
        "male_count": male_count,
        "female_count": female_count,
        "procedures_return_30": procedures_return_30,
        "procedures_first_30": procedures_first_30,
        "insurance_particular_30": insurance_particular_30,
        "insurance_convenio_30": insurance_convenio_30,
        "pdf_analyses_last7": pdf_analyses_last7,
        "low_stock": low_stock,
        "quotes_total": quotes_total,
        "quotes_responded": quotes_responded,
        "quotes_pending": quotes_pending,
        "quotes_items": quotes_items,
        "notifications_unread": 0,
        "trial_active": bool(u.trial_expiration and u.trial_expiration >= datetime.utcnow().date()),
    }


@app.route('/api/dashboard', methods=['GET'])
@login_required
def dashboard_api():
    u = current_user()
    return _jsonify_with_cache(_build_dashboard_payload(u), max_age=60, stale_while_revalidate=120)


@app.route('/index')
@login_required
def index():
    return serve_react_index()

# ------------------------------------------------------------------------------
# Admin
# ------------------------------------------------------------------------------
@app.route('/admin')
@login_required
def admin_page():
    guard = _admin_guard_response()
    if guard:
        return guard
    return serve_react_index()

@app.route('/api/admin/users', methods=['GET'])
@login_required
def admin_users_api():
    guard = _admin_guard_response()
    if guard:
        return guard

    users = User.query.order_by(User.created_at.desc()).all()
    return jsonify({"success": True, "users": [_serialize_admin_user(user) for user in users]})

@app.route('/api/admin/users/<int:user_id>/subscription', methods=['POST'])
@login_required
def admin_extend_subscription(user_id: int):
    guard = _admin_guard_response()
    if guard:
        return guard

    payload = request.get_json(silent=True) or {}
    period = (payload.get("period") or payload.get("plan") or "").strip().lower()
    if period in {"month", "monthly"}:
        plan = "monthly"
    elif period in {"year", "yearly"}:
        plan = "yearly"
    else:
        return jsonify({"success": False, "error": "Periodo inválido."}), 400

    user = User.query.get_or_404(user_id)
    if _is_admin_user(user) and user.id != current_user().id:
        return jsonify({"success": False, "error": "Não é possível alterar o admin."}), 400

    try:
        _extend_user_subscription(user, plan)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 400

    return jsonify({"success": True, "user": _serialize_admin_user(user)})

@app.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
@login_required
def admin_delete_user(user_id: int):
    guard = _admin_guard_response()
    if guard:
        return guard

    user = User.query.get_or_404(user_id)
    if _is_admin_user(user):
        return jsonify({"success": False, "error": "Não é possível remover o admin."}), 400

    try:
        _delete_user_account(user)
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({"success": False, "error": "Nao foi possivel remover o usuario."}), 500

    return jsonify({"success": True})

@app.route('/api/admin/users/<int:user_id>/credits', methods=['POST'])
@login_required
def admin_add_credits(user_id: int):
    guard = _admin_guard_response()
    if guard:
        return guard

    payload = request.get_json(silent=True) or {}
    amount = _coerce_int(payload.get("amount"), default=0)
    if amount <= 0:
        return jsonify({"success": False, "error": "Quantidade invalida."}), 400

    user = User.query.get_or_404(user_id)

    try:
        pkg, _changed = _ensure_package_usage(user, base_total=DEFAULT_FREE_ANALYSIS_ALLOWANCE)
        pkg.total = _coerce_int(getattr(pkg, "total", DEFAULT_FREE_ANALYSIS_ALLOWANCE), default=DEFAULT_FREE_ANALYSIS_ALLOWANCE) + amount
        db.session.add(pkg)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 400

    return jsonify({"success": True, "user": _serialize_admin_user(user)})

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
        if pacote not in price_map:
            flash('Selecione um pacote válido.', 'warning')
            return redirect(url_for('payments'))
        price_id = price_map.get(pacote) or ""

        try:
            session = _create_package_checkout_session(
                user=current_user(),
                package=int(pacote),
                price_id=price_id,
            )
            print(f"[Stripe] ✅ Sessão criada para pacote {pacote}")
            return redirect(session.url or url_for('payments'), code=303)

        except Exception as e:
            print("[Stripe] ❌ Erro ao criar sessão:", e)
            return _stripe_checkout_error_redirect(current_user(), "checkout_error")

    # Se for GET, entrega a aplicação React
    return serve_react_index()


@app.route('/payments', methods=['GET'])
@login_required
def payments():
    """
    Página única que permite:
    - Comprar pacotes de análises
    - Assinar plano mensal
    """
    return serve_react_index()

# ------------------------------------------------------------------------------
# Conta
# ------------------------------------------------------------------------------
@app.route('/account')
@login_required
def account():
    return serve_react_index()


@app.route('/api/account', methods=['GET'])
@login_required
def account_api():
    """
    Dados da conta para o dashboard em React.
    """
    u = current_user()
    now = datetime.utcnow()

    trial_expiration = getattr(u, "trial_expiration", None)
    if trial_expiration:
        remaining_td = trial_expiration - now.date()
        remaining_days = max(0, remaining_td.days)
        trial_active = (trial_expiration >= now.date())
    else:
        remaining_days = 0
        trial_active = False

    plan_status = (getattr(u, "plan_status", None) or "inactive").lower()
    plan_expiration = getattr(u, "plan_expiration", None)
    is_paid_active = False
    if plan_status == "paid":
        if (plan_expiration is None) or (plan_expiration and plan_expiration >= now):
            is_paid_active = True

    profile_image = (u.profile_image or DEFAULT_USER_IMAGE).strip()
    if not profile_image:
        profile_image = DEFAULT_USER_IMAGE
    if not profile_image.startswith(("/files/img/", "/static/")):
        profile_image = url_for("static", filename=profile_image)

    plan_name = (getattr(u, "plan", "") or "").lower()
    plan_labels = {
        "monthly": "Mensal",
        "yearly": "Anual",
    }

    messages = [
        {"category": category, "message": message}
        for category, message in get_flashed_messages(with_categories=True)
    ]

    return jsonify({
        "user": {
            "id": u.id,
            "username": getattr(u, "username", "") or "",
            "name": getattr(u, "name", "") or "",
            "email": getattr(u, "email", "") or "",
            "clinic_phone": getattr(u, "clinic_phone", "") or "",
            "clinic_address": getattr(u, "clinic_address", "") or "",
            "profile_image": profile_image,
        },
        "plan": {
            "status": plan_status,
            "name": plan_name or None,
            "label": plan_labels.get(plan_name) if plan_name else None,
            "expires_at": plan_expiration.strftime("%Y-%m-%d") if plan_expiration else None,
            "is_active": is_paid_active,
        },
        "trial": {
            "active": trial_active,
            "remaining_days": int(remaining_days),
            "expires_at": trial_expiration.strftime("%Y-%m-%d") if trial_expiration else None,
        },
        "notifications_unread": 0,
        "messages": messages,
    })

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
    return redirect(url_for('prices'))

# ------------------------------------------------------------------------------
# Stripe Subscription Integration
# ------------------------------------------------------------------------------
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

STRIPE_PRICE_MONTHLY = os.getenv("STRIPE_PRICE_MONTHLY", "")
STRIPE_PRICE_YEARLY = os.getenv("STRIPE_PRICE_YEARLY", "")
STRIPE_PRICE_PACKAGE_50 = os.getenv("STRIPE_PRICE_PACKAGE_50", "")
STRIPE_PRICE_PACKAGE_150 = os.getenv("STRIPE_PRICE_PACKAGE_150", "")
STRIPE_PRICE_PACKAGE_500 = os.getenv("STRIPE_PRICE_PACKAGE_500", "")
PACKAGE_PRICE_CENTS = {
    50: 12000,
    150: 30000,
    500: 80000,
}

def _stripe_checkout_error_redirect(user: User, code: str):
    status = _build_trial_status(user)
    target = "trial_locked" if status.get("trial_expired") else "payments"
    return redirect(url_for(target, error=code))

def _package_amount_cents(package: int) -> Optional[int]:
    return PACKAGE_PRICE_CENTS.get(package)

def _create_package_checkout_session(*, user: User, package: int, price_id: str):
    amount_cents = _package_amount_cents(package)
    if amount_cents is None:
        raise ValueError("Pacote inválido.")

    def _create(line_items):
        return stripe.checkout.Session.create(
            mode="payment",
            payment_method_types=["card", "boleto"],
            line_items=line_items,
            success_url=f"{_external_endpoint_url('payments')}?success=true",
            cancel_url=f"{_external_endpoint_url('payments')}?canceled=true",
        )

    if price_id:
        try:
            return _create([{"price": price_id, "quantity": 1}])
        except stripe.error.InvalidRequestError as exc:  # type: ignore[attr-defined]
            param = (getattr(exc, "param", "") or "").lower()
            message = str(exc).lower()
            if "price" not in param and "price" not in message:
                raise
            current_app.logger.warning(
                "[Stripe] Price ID inválido para pacote %s (%s): %s",
                package,
                price_id,
                exc,
            )

    return _create([{
        "price_data": {
            "currency": "brl",
            "unit_amount": int(amount_cents),
            "product_data": {"name": f"Pacote {package} analises"},
        },
        "quantity": 1,
    }])

def _create_subscription_checkout_session(
    *,
    user: User,
    plan: str,
    price_id: str,
    amount_cents: int,
    interval: str,
    plan_name: str,
):
    payment_methods = ["card", "boleto"]

    def _create(line_items):
        return stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=payment_methods,
            line_items=line_items,
            metadata={"user_id": str(user.id), "plan": plan},
            success_url=f"{_external_endpoint_url('subscription_success')}?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{_external_endpoint_url('payments')}?canceled=true",
        )

    def _create_with_fallback(line_items):
        try:
            return _create(line_items)
        except stripe.error.InvalidRequestError as exc:  # type: ignore[attr-defined]
            param = (getattr(exc, "param", "") or "").lower()
            message = str(exc).lower()
            if "payment_method_types" in param or "payment_method_types" in message or "boleto" in message:
                if "boleto" in payment_methods:
                    current_app.logger.warning(
                        "[Stripe] Boleto indisponivel para assinatura. Usando cartao. (%s)",
                        exc,
                    )
                    return stripe.checkout.Session.create(
                        mode="subscription",
                        payment_method_types=["card"],
                        line_items=line_items,
                        metadata={"user_id": str(user.id), "plan": plan},
                        success_url=f"{_external_endpoint_url('subscription_success')}?session_id={{CHECKOUT_SESSION_ID}}",
                        cancel_url=f"{_external_endpoint_url('payments')}?canceled=true",
                    )
            raise

    if price_id:
        try:
            return _create_with_fallback([{"price": price_id, "quantity": 1}])
        except stripe.error.InvalidRequestError as exc:  # type: ignore[attr-defined]
            current_app.logger.warning(
                "[Stripe] Price ID inválido para %s (%s): %s",
                plan,
                price_id,
                exc,
            )
        except Exception:
            raise

    return _create_with_fallback([{
        "price_data": {
            "currency": "brl",
            "unit_amount": int(amount_cents),
            "product_data": {"name": plan_name},
            "recurring": {"interval": interval},
        },
        "quantity": 1,
    }])

@app.route("/subscribe_pay_mensal")
@login_required
def subscribe_pay_mensal():
    """Gera link de pagamento do Stripe para o plano mensal (R$ 79,90)."""
    user = current_user()
    if not stripe.api_key or not STRIPE_PRICE_MONTHLY:
        current_app.logger.error("[Stripe] Configuracao incompleta para plano mensal.")
        if not stripe.api_key:
            return _stripe_checkout_error_redirect(user, "checkout_unavailable")
    try:
        session = _create_subscription_checkout_session(
            user=user,
            plan="monthly",
            price_id=STRIPE_PRICE_MONTHLY,
            amount_cents=7990,
            interval="month",
            plan_name="Plano Mensal Ponza Health",
        )
    except Exception:
        current_app.logger.exception("[Stripe] Falha ao criar sessao de checkout mensal.")
        return _stripe_checkout_error_redirect(user, "checkout_error")
    print("[Stripe] ✅ Sessão criada: plano mensal")
    url = session.url or url_for("payments")
    return redirect(url, code=303)

@app.route("/subscribe_pay_anual")
@login_required
def subscribe_pay_anual():
    """Gera link de pagamento do Stripe para o plano anual (R$ 838,80)."""
    user = current_user()
    if not stripe.api_key or not STRIPE_PRICE_YEARLY:
        current_app.logger.error("[Stripe] Configuracao incompleta para plano anual.")
        if not stripe.api_key:
            return _stripe_checkout_error_redirect(user, "checkout_unavailable")
    try:
        session = _create_subscription_checkout_session(
            user=user,
            plan="yearly",
            price_id=STRIPE_PRICE_YEARLY,
            amount_cents=83880,
            interval="year",
            plan_name="Plano Anual Ponza Health",
        )
    except Exception:
        current_app.logger.exception("[Stripe] Falha ao criar sessao de checkout anual.")
        return _stripe_checkout_error_redirect(user, "checkout_error")
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
    if package not in price_map:
        flash("Pacote inválido.", "danger")
        return redirect(url_for("payments"))
    price_id = price_map.get(package) or ""
    try:
        session = _create_package_checkout_session(
            user=current_user(),
            package=package,
            price_id=price_id,
        )
    except Exception:
        current_app.logger.exception("[Stripe] Falha ao criar sessao de checkout do pacote.")
        return _stripe_checkout_error_redirect(current_user(), "checkout_error")
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

        user = User.query.get(int(user_id)) if user_id else None
        if user:
            normalized_plan = (plan or '').strip().lower()
            if normalized_plan not in {'monthly', 'yearly'}:
                normalized_plan = 'monthly'

            previous_plan = (user.plan or '').strip().lower()
            _apply_plan_allowance(user, normalized_plan, previous_plan=previous_plan)

            user.plan_status = 'paid'
            user.plan = normalized_plan
            user.trial_expiration = None

            if normalized_plan == 'yearly':
                user.plan_expiration = datetime.utcnow() + timedelta(days=365)
            else:
                user.plan_expiration = datetime.utcnow() + timedelta(days=30)

            db.session.commit()
            print(f"[Stripe] Plano {normalized_plan} ativado para o usuário {user.email}")
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
    clinic_address = (request.form.get("clinic_address") or "").strip()
    birthdate_str = (request.form.get("birthdate") or "").strip()
    email = (request.form.get("email") or "").strip().lower()

    if name:
        u.name = name

    if clinic_phone:
        u.clinic_phone = clinic_phone

    u.clinic_address = clinic_address or None

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


def _load_reference_table() -> dict:
    path = _project_references_json()
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("Invalid references payload — expected mapping with test definitions.")
    return payload


def _save_reference_table(payload: dict) -> None:
    path = _project_references_json()
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

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
        return serve_react_index()

    use_ai = str(request.form.get('use_ai') or '').lower() in {'1', 'true', 'on', 'yes'}

    # ==========================================================
    # ENTRADA MANUAL
    # ==========================================================
    if request.form.get('manual_entry') == '1':
        return _handle_manual_entry(request, u, analyze_pdf, use_ai=use_ai)

    # ==========================================================
    # UPLOAD DE PDF
    # ==========================================================
    return _handle_pdf_upload(request, u, analyze_pdf, use_ai=use_ai)


@app.route('/api/references', methods=['GET', 'PUT'])
@login_required
def api_references():
    if request.method == 'GET':
        try:
            table = _load_reference_table()
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500
        return jsonify({"success": True, "references": table})

    payload = request.get_json(silent=True) or {}
    updates = payload.get("updates") or []
    if isinstance(updates, dict):
        updates = [{"name": key, "ideal": value} for key, value in updates.items()]
    if not isinstance(updates, list):
        return jsonify({"success": False, "error": "Formato inválido para updates."}), 400

    try:
        table = _load_reference_table()
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500

    updated = 0
    created = 0

    def find_existing_key(raw_name: str) -> str | None:
        lowered = raw_name.lower()
        for key in table.keys():
            if key.lower() == lowered:
                return key
        return None

    for item in updates:
        if not isinstance(item, dict):
            continue
        name = (item.get("name") or "").strip()
        if not name:
            continue
        ideal = item.get("ideal")
        if ideal is None:
            continue
        ideal_text = str(ideal).strip()
        if not ideal_text:
            continue
        existing_key = find_existing_key(name)
        if existing_key:
            entry = table.get(existing_key)
            if not isinstance(entry, dict):
                entry = {}
                table[existing_key] = entry
            if entry.get("ideal") == ideal_text:
                continue
            entry["ideal"] = ideal_text
            updated += 1
            continue

        table[name] = {"ideal": ideal_text, "medications": {"low": "", "high": ""}}
        created += 1

    if updated or created:
        try:
            _save_reference_table(table)
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500
    return jsonify({"success": True, "updated": updated, "created": created})


@app.route('/api/upload', methods=['POST'])
@login_required
def api_upload():
    from prescription import analyze_pdf

    u = current_user()
    use_ai = str(request.form.get('use_ai') or '').lower() in {'1', 'true', 'on', 'yes'}
    is_bioresonancia = str(request.form.get('bioresonancia') or '').lower() in {'1', 'true', 'on', 'yes'}
    wants_stream = str(request.form.get('stream') or '').lower() in {'1', 'true', 'yes'}
    if wants_stream:
        return _stream_upload_response(request, u, analyze_pdf, use_ai=use_ai, is_bioresonancia=is_bioresonancia)

    if request.form.get('manual_entry') == '1':
        ok, payload = _process_manual_entry_payload(request.form, u, analyze_pdf, use_ai=use_ai)
    else:
        ok, payload = _process_pdf_upload_payload(request, u, analyze_pdf, use_ai=use_ai, is_bioresonancia=is_bioresonancia)

    if not ok:
        return jsonify({"success": False, "error": payload.get("error")}), 400

    return jsonify({"success": True, **payload})


def _stream_upload_response(request, u, analyze_pdf, *, use_ai: bool, is_bioresonancia: bool = False):
    def sse_event(name: str, data: dict[str, Any]) -> str:
        payload = json.dumps(data, ensure_ascii=False)
        return f"event: {name}\ndata: {payload}\n\n"

    def generate():
        step_msg = "Upload recebido. Iniciando análise de Bioressonância..." if is_bioresonancia else "Upload recebido. Iniciando análise..."
        yield sse_event("status", {"step": "upload", "message": step_msg})
        timings: dict[str, Any] = {}
        if request.form.get('manual_entry') == '1':
            ok, payload = _process_manual_entry_payload(request.form, u, analyze_pdf, use_ai=use_ai, timings=timings)
        else:
            ok, payload = _process_pdf_upload_payload(request, u, analyze_pdf, use_ai=use_ai, timings=timings, is_bioresonancia=is_bioresonancia)
        if not ok:
            yield sse_event("error", {"error": payload.get("error") or "Falha ao processar o envio."})
            return
        payload["timings"] = payload.get("timings") or timings
        yield sse_event("done", payload)

    response = current_app.response_class(stream_with_context(generate()), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    return response


# =====================================================================
# Helpers internos para manter a rota enxuta
# =====================================================================

def _process_manual_entry_payload(form, u, analyze_pdf, *, use_ai=False, timings: dict[str, Any] | None = None) -> tuple[bool, dict[str, Any]]:
    timings = timings or {}
    name = (form.get('name') or '').strip()
    age = (form.get('age') or '').strip()
    cpf = (form.get('cpf') or '').strip()
    gender = (form.get('gender') or '').strip()
    phone = (form.get('phone') or '').strip()
    doctor_name = (form.get('doctor') or '').strip()
    doctor_phone = (form.get('doctor_phone') or '').strip()
    patient_name = (form.get('patient_name') or '').strip()
    patient_phone = (form.get('patient_phone') or '').strip()
    lab_results = (form.get('lab_results') or '').strip()

    send_doctor = form.get('send_doctor') == '1'
    send_patient = form.get('send_patient') == '1'

    if not lab_results:
        return False, {"error": "Digite os resultados no campo de texto."}

    pkg, remaining = _analysis_package_status(u)
    if remaining <= 0:
        return False, {
            "error": "Seu pacote de análises acabou. Compre mais créditos para continuar usando o Ponza Lab."
        }

    refs_path = _project_references_json()
    analysis_start = time.perf_counter()
    dgn, rx, *_ = analyze_pdf(
        lab_results,
        references_path=refs_path,
        manual=True,
        manual_overrides={
            'name': name,
            'age': age,
            'gender': gender,
            'phone': phone,
        },
        use_ai=use_ai,
    )
    timings["openai_ms"] = round((time.perf_counter() - analysis_start) * 1000)

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

    _consume_analysis_slot(pkg)
    try:
        current_app.logger.info("[Ponza Lab] Timings manual entry: %s", timings)
    except Exception:
        pass
    return True, {"redirect_url": url_for('result', patient_id=p.id), "patient_id": p.id, "timings": timings}


def _process_pdf_upload_payload(
    request,
    u,
    analyze_pdf,
    *,
    use_ai: bool = False,
    timings: dict[str, Any] | None = None,
    is_bioresonancia: bool = False,
) -> tuple[bool, dict[str, Any]]:
    timings = timings or {}
    file = request.files.get('pdf_file')
    if not file or not file.filename.lower().endswith('.pdf'):
        return False, {"error": "Nenhum PDF válido enviado."}

    upload_start = time.perf_counter()
    content = file.read()
    timings["upload_ms"] = round((time.perf_counter() - upload_start) * 1000)
    if not content:
        return False, {"error": "PDF vazio ou inválido."}

    pkg, remaining = _analysis_package_status(u)
    if remaining <= 0:
        return False, {
            "error": "Seu pacote de análises acabou. Compre mais créditos para continuar usando o Ponza Lab."
        }

    db_start = time.perf_counter()
    sf = SecureFile(
        user_id=u.id,
        kind="upload_pdf_bioresonancia" if is_bioresonancia else "upload_pdf",
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
    timings["db_file_save_ms"] = round((time.perf_counter() - db_start) * 1000)

    manual_name = (request.form.get('patient_manual_name') or '').strip()
    manual_age = (request.form.get('patient_manual_age') or '').strip()
    manual_gender = (request.form.get('patient_manual_sex') or '').strip()
    manual_phone = (request.form.get('patient_manual_phone') or '').strip()

    manual_birthdate_str = None
    if manual_age:
        try:
            age_int = int(manual_age)
            today = date.today()
            candidate_year = max(1900, today.year - age_int)
            manual_birthdate_str = date(candidate_year, today.month, today.day).strftime('%d/%m/%Y')
        except ValueError:
            manual_birthdate_str = None

    manual_overrides: dict[str, str] = {}
    if manual_name:
        manual_overrides["nome"] = manual_name
    if manual_gender:
        manual_overrides["sexo"] = manual_gender
    if manual_birthdate_str:
        manual_overrides["data_nascimento"] = manual_birthdate_str
    if manual_phone:
        manual_overrides["telefone"] = manual_phone

    send_doctor = request.form.get('send_doctor') == '1'
    send_patient = request.form.get('send_patient') == '1'

    doctor_name_input = (request.form.get('doctor_name') or '').strip()
    doctor_phone = (request.form.get('doctor_phone') or '').strip()
    patient_name = (request.form.get('patient_name') or '').strip()
    patient_phone = (request.form.get('patient_phone') or '').strip()

    clinic_contact = (u.clinic_phone or u.name or u.username or '').strip() or '-'
    doctor_display = doctor_name_input or (getattr(u, "name", None) or u.username)

    if use_ai:
        # First, try to identify the patient to get previous exam history
        # We do a preliminary patient lookup based on manual overrides or extracted data
        preliminary_patient = None
        preliminary_cpf = manual_overrides.get("cpf", "").strip()
        preliminary_name = manual_overrides.get("nome", "").strip() or manual_name
        
        if preliminary_cpf:
            preliminary_patient = Patient.query.filter_by(user_id=u.id, cpf=preliminary_cpf).first()
        if not preliminary_patient and preliminary_name:
            preliminary_patient = Patient.query.filter_by(user_id=u.id, name=preliminary_name).first()
        
        # Get previous exam results for comparison if patient exists (not for bioresonância)
        previous_results = None
        if preliminary_patient and not is_bioresonancia:
            previous_results = _get_patient_previous_exam(u.id, preliminary_patient.id)
        
        try:
            if is_bioresonancia:
                analysis = _perform_bioresonancia_analysis(
                    content,
                    manual_overrides,
                    timings=timings,
                )
            else:
                analysis = _perform_ai_lab_analysis(
                    content,
                    manual_overrides,
                    timings=timings,
                    previous_results=previous_results,
                )
        except RuntimeError as exc:
            return False, {"error": str(exc)}

        patient_block = analysis.get("paciente") or {}
        db_analysis_start = time.perf_counter()
        patient = _get_or_create_patient(
            u,
            name=patient_block.get("nome"),
            cpf=(patient_block.get("cpf") or "").strip(),
            gender=patient_block.get("sexo"),
            phone=manual_phone or patient_block.get("telefone"),
            birthdate=patient_block.get("data_nascimento"),
        )

        if doctor_name_input:
            _assign_doctor_to_patient(u, patient, doctor_name_input)

        diagnosis_text = analysis.get("resumo_clinico") or ""
        prescription_text = "\n".join(analysis.get("prescricao") or [])
        _attach_consult_and_notes(patient, diagnosis_text, prescription_text)

        pf.patient_id = patient.id
        db.session.add(pf)
        db.session.commit()
        
        # Save exam history for future comparisons
        try:
            _save_patient_exam_history(
                user_id=u.id,
                patient_id=patient.id,
                exam_date=datetime.today().date(),
                resumo_clinico=diagnosis_text,
                abnormal_results=analysis.get("abnormal_exams") or [],
                all_results=analysis.get("raw_exams") or analysis.get("exames") or [],
                pdf_file_id=pf.id,
            )
        except Exception as exc:
            # Don't fail the analysis if history save fails
            try:
                current_app.logger.warning("[Ponza Lab] Failed to save exam history: %s", exc)
            except Exception:
                pass
        
        timings["db_save_ms"] = round((time.perf_counter() - db_analysis_start) * 1000)

        context = _build_analysis_context(analysis, file_name=file.filename, doctor_name=doctor_display)
        
        # Add comparison data to context if available
        if analysis.get("has_comparison"):
            context["has_comparison"] = True
            context["previous_exam_date"] = analysis.get("previous_exam_date")
            context["comparacao_exames"] = analysis.get("comparacao_exames") or []
            context["evolucao_clinica"] = analysis.get("evolucao_clinica") or ""
        
        lab_pdf_bytes = generate_lab_analysis_pdf_bytes(
            patient=patient,
            context=context,
            doctor_display_name=doctor_display,
        )

        if send_doctor and doctor_phone:
            send_pdf_whatsapp_template(
                "relatorio_ponza",
                doctor_name_input or doctor_display,
                patient.name,
                doctor_phone,
                patient.id,
                clinic_contact=clinic_contact,
                link_kind="lab_analysis_pdf",
            )
            old_pdf_bytes = generate_result_pdf_bytes(
                patient=patient,
                diagnostic_text=diagnosis_text,
                prescription_text=prescription_text,
                doctor_display_name=doctor_display,
            )
            try_send_whatsapp_pdf(
                doctor_phone,
                lab_pdf_bytes,
                f"Analise_{(patient.name or 'Paciente').replace(' ', '_')}.pdf",
            )
            try_send_whatsapp_pdf(
                doctor_phone,
                old_pdf_bytes,
                f"Resultado_{(patient.name or 'Paciente').replace(' ', '_')}.pdf",
            )

        if send_patient and patient_phone:
            send_pdf_whatsapp_patient(
                patient_name or patient.name,
                patient_phone,
                patient.id,
                clinic_phone=u.clinic_phone,
                link_kind="lab_analysis_pdf",
            )

        _consume_analysis_slot(pkg)
        serializer = URLSafeSerializer(app.config['SECRET_KEY'], salt="lab-analysis-pdf")
        token_payload = {
            "patient": context.get("patient") or {},
            "doctor_name": context.get("doctor_name"),
            "exams": context.get("exams") or [],
            "abnormal_exams": context.get("abnormal_exams") or [],
            "prescription": context.get("prescription") or [],
            "summary": context.get("summary") or "",
            "orientations": context.get("orientations") or [],
            "alerts": context.get("alerts") or [],
            "file_name": context.get("file_name"),
            # Add comparison data to token payload
            "has_comparison": context.get("has_comparison", False),
            "previous_exam_date": context.get("previous_exam_date"),
            "comparacao_exames": context.get("comparacao_exames") or [],
            "evolucao_clinica": context.get("evolucao_clinica") or "",
        }
        analysis_token = serializer.dumps(token_payload)

        try:
            current_app.logger.info("[Ponza Lab] Timings AI PDF: %s", timings)
        except Exception:
            pass
        return True, {
            "redirect_url": url_for('lab_analysis_view', token=analysis_token),
            "analysis_token": analysis_token,
            "patient_id": patient.id,
            "timings": timings,
            "has_comparison": context.get("has_comparison", False),
        }

    refs_path = _project_references_json()
    analysis_start = time.perf_counter()
    dgn, rx, name_ai, gender_ai, age_ai, cpf_ai, phone_ai, doctor_ai, birth_ai = analyze_pdf(
        content,
        references_path=refs_path,
        manual=False,
        manual_overrides={
            'name': manual_name,
            'age': manual_age,
            'gender': manual_gender,
            'phone': manual_phone,
        },
        use_ai=use_ai,
    )
    timings["openai_ms"] = round((time.perf_counter() - analysis_start) * 1000)

    p = _get_or_create_patient(
        u,
        name=manual_name or name_ai,
        cpf=(cpf_ai or '').strip(),
        gender=manual_gender or gender_ai,
        phone=manual_phone or phone_ai,
        birthdate=manual_birthdate_str or birth_ai,
    )

    if doctor_ai:
        _assign_doctor_to_patient(u, p, doctor_ai)

    db_analysis_start = time.perf_counter()
    _attach_consult_and_notes(p, dgn, rx)
    pf.patient_id = p.id
    db.session.commit()
    timings["db_save_ms"] = round((time.perf_counter() - db_analysis_start) * 1000)

    if send_doctor and doctor_phone:
        send_pdf_whatsapp_template(
            "relatorio_ponza",
            doctor_name_input,
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

    _consume_analysis_slot(pkg)
    try:
        current_app.logger.info("[Ponza Lab] Timings classic PDF: %s", timings)
    except Exception:
        pass
    return True, {"redirect_url": url_for('result', patient_id=p.id), "patient_id": p.id, "timings": timings}


def _handle_manual_entry(request, u, analyze_pdf, *, use_ai=False):
    """Processa inserção manual de resultados."""
    ok, payload = _process_manual_entry_payload(request.form, u, analyze_pdf, use_ai=use_ai)
    if not ok:
        return redirect(url_for('upload', error=payload.get("error")))
    return redirect(payload["redirect_url"])

def _handle_pdf_upload(request, u, analyze_pdf, *, use_ai=False):
    """Processa upload de arquivo PDF, analisa e envia relatórios via WhatsApp."""
    ok, payload = _process_pdf_upload_payload(request, u, analyze_pdf, use_ai=use_ai)
    if not ok:
        return redirect(url_for('upload', error=payload.get("error")))
    return redirect(payload["redirect_url"])


def _handle_pdf_upload_ai(
    *,
    user,
    file_bytes: bytes,
    file_name: str,
    manual_overrides: dict[str, str],
    manual_phone: str,
    doctor_text: str,
    doctor_display: str,
    send_doctor: bool,
    send_patient: bool,
    doctor_phone: str,
    patient_name_field: str,
    patient_phone_field: str,
    clinic_contact: str,
    pdf_entry: PdfFile,
):
    """Executa a análise via IA e renderiza o painel do Ponza Lab."""
    try:
        analysis = _perform_ai_lab_analysis(file_bytes, manual_overrides)
    except RuntimeError as exc:
        return redirect(url_for('upload', error=str(exc)))

    patient_block = analysis.get("paciente") or {}
    patient = _get_or_create_patient(
        user,
        name=patient_block.get("nome"),
        cpf=(patient_block.get("cpf") or "").strip(),
        gender=patient_block.get("sexo"),
        phone=manual_phone or patient_block.get("telefone"),
        birthdate=patient_block.get("data_nascimento"),
    )

    if doctor_text:
        _assign_doctor_to_patient(user, patient, doctor_text)

    diagnosis_text = analysis.get("resumo_clinico") or ""
    prescription_text = "\n".join(analysis.get("prescricao") or [])
    _attach_consult_and_notes(patient, diagnosis_text, prescription_text)

    pdf_entry.patient_id = patient.id
    db.session.add(pdf_entry)
    db.session.commit()

    if send_doctor and doctor_phone:
        send_pdf_whatsapp_template(
            "relatorio_ponza",
            doctor_text or doctor_display,
            patient.name,
            doctor_phone,
            patient.id,
            clinic_contact=clinic_contact,
        )

    if send_patient and patient_phone_field:
        send_pdf_whatsapp_patient(
            patient_name_field or patient.name,
            patient_phone_field,
            patient.id,
            clinic_phone=user.clinic_phone
        )

    context = _build_analysis_context(analysis, file_name=file_name, doctor_name=doctor_display)
    serializer = URLSafeSerializer(app.config['SECRET_KEY'], salt="lab-analysis-pdf")
    token_payload = {
        "patient": context.get("patient") or {},
        "doctor_name": context.get("doctor_name"),
        "exams": context.get("exams") or [],
        "abnormal_exams": context.get("abnormal_exams") or [],
        "prescription": context.get("prescription") or [],
        "summary": context.get("summary") or "",
        "orientations": context.get("orientations") or [],
        "alerts": context.get("alerts") or [],
        "file_name": context.get("file_name"),
    }
    analysis_token = serializer.dumps(token_payload)

    return redirect(url_for('lab_analysis_view', token=analysis_token))


def _get_patient_previous_exam(user_id: int, patient_id: int) -> dict[str, Any] | None:
    """
    Retrieve the most recent exam history for a patient to enable comparison.
    Returns dict with 'exames' and 'resumo_clinico' or None if no history.
    """
    history = (
        PatientExamHistory.query
        .filter_by(user_id=user_id, patient_id=patient_id)
        .order_by(PatientExamHistory.exam_date.desc(), PatientExamHistory.created_at.desc())
        .first()
    )
    if not history:
        return None
    
    try:
        all_results = json.loads(history.all_results) if history.all_results else []
    except (json.JSONDecodeError, TypeError):
        all_results = []
    
    return {
        "exames": all_results,
        "resumo_clinico": history.resumo_clinico or "",
        "exam_date": history.exam_date.isoformat() if history.exam_date else None,
    }


def _save_patient_exam_history(
    *,
    user_id: int,
    patient_id: int,
    exam_date: date,
    resumo_clinico: str,
    abnormal_results: list[dict[str, Any]],
    all_results: list[dict[str, Any]],
    pdf_file_id: int | None = None,
) -> PatientExamHistory:
    """Save exam results to history for future comparison."""
    history = PatientExamHistory(
        user_id=user_id,
        patient_id=patient_id,
        exam_date=exam_date,
        resumo_clinico=resumo_clinico,
        abnormal_results=json.dumps(abnormal_results, ensure_ascii=False) if abnormal_results else None,
        all_results=json.dumps(all_results, ensure_ascii=False) if all_results else None,
        pdf_file_id=pdf_file_id,
    )
    db.session.add(history)
    db.session.commit()
    return history


def _build_resumo_clinico_from_abnormal(
    abnormal_exams: list[dict[str, Any]],
    existing_resumo: str | None = None
) -> str:
    """
    Return the AI-generated resumo clinico without modification.
    The resumo should be a professional medical summary without listing values.
    """
    # If AI generated a proper resumo, use it
    if existing_resumo and existing_resumo.strip():
        return existing_resumo.strip()
    
    # Fallback if no resumo was generated
    if not abnormal_exams:
        return "Exames laboratoriais dentro dos parâmetros de normalidade. Não foram identificadas alterações significativas que necessitem de intervenção imediata."
    
    # Generic fallback for when AI fails to generate resumo but there are alterations
    return "Análise laboratorial apresenta valores alterados que requerem avaliação clínica. Recomenda-se correlação com quadro clínico do paciente e acompanhamento médico."


def _perform_ai_lab_analysis(
    file_bytes: bytes,
    overrides: dict[str, str],
    *,
    timings: dict[str, Any] | None = None,
    previous_results: dict[str, Any] | None = None,
) -> dict[str, Any]:
    timings = timings or {}
    payload = extract_exam_payload(file_bytes, require_ocr=False, timings=timings)
    ai_response = generate_ai_analysis(payload, timings=timings, previous_results=previous_results)
    if not ai_response.get("ok"):
        raise RuntimeError(ai_response.get("error") or "Falha ao analisar o PDF.")
    post_start = time.perf_counter()
    analysis = ai_response.get("analysis") or {}
    patient_block = analysis.get("paciente") or {}
    payload_patient = payload.get("patient") or {}
    for key in ("nome", "sexo", "data_nascimento", "cpf", "telefone"):
        if not patient_block.get(key) and payload_patient.get(key):
            patient_block[key] = payload_patient.get(key)
    analysis["paciente"] = patient_block
    for key, value in overrides.items():
        if value:
            patient_block[key] = value
    analysis.setdefault("exames", [])
    analysis.setdefault("orientações", [])
    analysis.setdefault("alertas", [])
    analysis["raw_exams"] = list(analysis.get("exames") or [])
    reference_table = payload.get("reference_table") or {}
    abnormal_exams, prescription = _apply_reference_rules(analysis, reference_table)
    analysis["abnormal_exams"] = abnormal_exams
    analysis["prescricao"] = prescription
    
    # Enhance resumo_clinico to always include abnormal values
    existing_resumo = analysis.get("resumo_clinico") or ""
    analysis["resumo_clinico"] = _build_resumo_clinico_from_abnormal(abnormal_exams, existing_resumo)
    
    # Add comparison data if previous results were provided
    if previous_results:
        analysis["has_comparison"] = True
        analysis["previous_exam_date"] = previous_results.get("exam_date")
        # comparacao_exames and evolucao_clinica should already be in analysis from AI
    
    timings["postprocess_ms"] = round((time.perf_counter() - post_start) * 1000)
    return analysis


def _perform_bioresonancia_analysis(
    file_bytes: bytes,
    overrides: dict[str, str],
    *,
    timings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Perform AI analysis specifically for Bioressonância files.
    Uses specialized extraction and AI prompts for large bioresonância PDFs.
    """
    timings = timings or {}
    
    # Use specialized bioresonância extraction
    max_pages = int(os.getenv("BIORESONANCIA_MAX_PAGES", "30"))
    payload = extract_bioresonancia_payload(file_bytes, timings=timings, max_pages=max_pages)
    
    # Use specialized bioresonância AI analysis
    ai_response = generate_bioresonancia_analysis(payload, timings=timings)
    if not ai_response.get("ok"):
        raise RuntimeError(ai_response.get("error") or "Falha ao analisar o arquivo de Bioressonância.")
    
    post_start = time.perf_counter()
    analysis = ai_response.get("analysis") or {}
    
    # Merge patient data from extraction and AI response
    patient_block = analysis.get("paciente") or {}
    payload_patient = payload.get("patient") or {}
    for key in ("nome", "sexo", "data_nascimento", "cpf", "telefone", "idade", "altura", "peso"):
        if not patient_block.get(key) and payload_patient.get(key):
            patient_block[key] = payload_patient.get(key)
    analysis["paciente"] = patient_block
    
    # Apply manual overrides
    for key, value in overrides.items():
        if value:
            patient_block[key] = value
    
    # Ensure required fields exist
    analysis.setdefault("exames", [])
    analysis.setdefault("orientações", [])
    analysis.setdefault("alertas", [])
    analysis["raw_exams"] = list(analysis.get("exames") or [])
    
    # For bioresonância, we don't apply external reference rules
    # The references are embedded in the document itself
    abnormal_exams = [
        exam for exam in analysis.get("exames") or []
        if str(exam.get("status", "")).lower() in ("alto", "baixo")
    ]
    analysis["abnormal_exams"] = abnormal_exams
    
    # Keep existing prescription from AI (bioresonância-specific recommendations)
    if not analysis.get("prescricao"):
        analysis["prescricao"] = []
    
    # Ensure resumo_clinico is comprehensive for bioresonância
    resumo = analysis.get("resumo_clinico") or ""
    if not resumo or len(resumo) < 50:
        # Build a basic summary from abnormal results
        if abnormal_exams:
            categories = set()
            for exam in abnormal_exams[:20]:
                cat = exam.get("categoria") or "Geral"
                categories.add(cat)
            cat_list = ", ".join(sorted(categories)[:5])
            resumo = f"Análise de Bioressonância identificou alterações nas seguintes áreas: {cat_list}. Recomenda-se avaliação clínica complementar e acompanhamento dos parâmetros alterados."
        else:
            resumo = "Análise de Bioressonância não identificou alterações significativas. Parâmetros avaliados dentro das faixas de normalidade estabelecidas pelo equipamento."
        analysis["resumo_clinico"] = resumo
    
    # Mark as bioresonância analysis
    analysis["is_bioresonancia"] = True
    
    timings["postprocess_ms"] = round((time.perf_counter() - post_start) * 1000)
    return analysis


def _format_patient_details(patient: dict) -> list[tuple[str, str]]:
    ordered_keys = [
        ("nome", "Nome"),
        ("cpf", "CPF"),
        ("data_nascimento", "Data de nascimento"),
        ("sexo", "Sexo"),
    ]
    seen = {key for key, _ in ordered_keys}
    details: list[tuple[str, str]] = []
    for key, label in ordered_keys:
        value = patient.get(key)
        if value:
            details.append((label, value))
    for key, value in patient.items():
        if key in seen or not value:
            continue
        details.append((key.replace("_", " ").title(), value))
    return details


def _is_abnormal_result(entry: dict) -> bool:
    status = str(entry.get("status") or entry.get("estado") or "").strip().lower()
    if not status:
        return False
    return status not in {"normal", "dentro", "adequado"}


def _build_analysis_context(analysis: dict[str, Any], *, file_name: str, doctor_name: str) -> dict[str, Any]:
    patient = analysis.get("paciente") or {}
    patient_gender = patient.get("sexo")
    exams_raw = analysis.get("raw_exams") or analysis.get("exames") or []
    exams = []
    for entry in exams_raw:
        reference_field = entry.get("referencia") or entry.get("reference")
        exams.append({
            **entry,
            "reference_display": _format_reference_label(reference_field, patient_gender),
        })
    abnormal = analysis.get("abnormal_exams") or []
    reference_table = {}
    try:
        reference_table = _load_reference_table()
    except Exception:
        reference_table = {}
    _apply_reference_overrides_to_exams(exams, gender=patient_gender, reference_table=reference_table)
    if abnormal:
        _apply_reference_overrides_to_exams(abnormal, gender=patient_gender, reference_table=reference_table)
    context = {
        "patient": patient,
        "patient_details": _format_patient_details(patient),
        "exams": exams,
        "abnormal_exams": abnormal if abnormal else [entry for entry in exams if _is_abnormal_result(entry)],
        "summary": analysis.get("resumo_clinico") or "",
        "prescription": analysis.get("prescricao") or [],
        "orientations": analysis.get("orientações") or [],
        "alerts": analysis.get("alertas") or [],
        "doctor_name": doctor_name,
        "file_name": file_name,
    }
    return context


def _parse_index_payload(raw_value: Optional[str]) -> set[int]:
    indexes: set[int] = set()
    if not raw_value:
        return indexes
    for chunk in raw_value.split(","):
        if not chunk:
            continue
        try:
            indexes.add(int(chunk.strip()))
        except ValueError:
            continue
    return indexes


def _parse_json_payload(raw_value: Optional[str]) -> Any:
    if not raw_value:
        return None
    try:
        return json.loads(raw_value)
    except Exception:
        return None


def _filter_excluded_items(items: list[Any], excluded_indexes: set[int]) -> list[Any]:
    if not items or not excluded_indexes:
        return items
    return [value for idx, value in enumerate(items) if idx not in excluded_indexes]


def _normalize_label(label: Optional[str]) -> str:
    if not label:
        return ""
    text = unicodedata.normalize("NFKD", label)
    stripped = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(stripped.lower().split())


def _build_reference_index(reference_table: dict) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for name, payload in reference_table.items():
        norm = _normalize_label(name)
        index[norm] = payload
        for alias in payload.get("synonyms") or []:
            alias_norm = _normalize_label(alias)
            index[alias_norm] = payload
    return index


def _match_reference_entry(name: str, index: dict[str, dict]) -> Optional[dict]:
    norm = _normalize_label(name)
    return index.get(norm)


def _coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    text = text.replace(" ", "")
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif text.count(".") == 1:
        integer, fraction = text.split(".")
        if len(fraction) == 3:
            text = integer + fraction
    try:
        return float(text)
    except ValueError:
        return None


def _parse_reference_bounds(reference_value: Any, gender: Optional[str]) -> tuple[Optional[float], Optional[float]]:
    if isinstance(reference_value, dict):
        keys = []
        if gender:
            initial = gender[:1].upper()
            keys.extend([gender, initial])
        keys.extend(reference_value.keys())
        for key in keys:
            if key in reference_value:
                bounds = _parse_reference_bounds(reference_value[key], None)
                if bounds != (None, None):
                    return bounds
        return (None, None)

    if isinstance(reference_value, list):
        for item in reference_value:
            bounds = _parse_reference_bounds(item, gender)
            if bounds != (None, None):
                return bounds
        return (None, None)

    if not isinstance(reference_value, str):
        return (None, None)

    text = reference_value.lower()
    text = text.replace("≤", "<=").replace("≥", ">=").replace("≦", "<=").replace("≧", ">=")
    range_match = re.search(r"(\d+(?:[.,]\d+)?)\s*[-–—]\s*(\d+(?:[.,]\d+)?)", text)
    if range_match:
        low = _coerce_float(range_match.group(1))
        high = _coerce_float(range_match.group(2))
        if low is not None and high is not None:
            return (low, high)

    tokens = re.findall(r"[-+]?\d+(?:[.,]\d+)?", text)
    numbers = [_coerce_float(token) for token in tokens]
    numbers = [num for num in numbers if num is not None]

    if not numbers:
        return (None, None)

    if re.search(r"(<=|<|\bmenor\b|\binferior\b|\bate\b|\babaixo\b)", text):
        return (None, numbers[0])
    if re.search(r"(>=|>|\bmaior\b|\bsuperior\b|\bacima\b)", text):
        return (numbers[0], None)
    if re.search(r"(=|\bigual\b)", text):
        return (numbers[0], numbers[0])
    if "entre" in text or " a " in text or "-" in text:
        if len(numbers) >= 2:
            return (numbers[0], numbers[1])
    if len(numbers) >= 2:
        return (numbers[0], numbers[1])
    return (None, None)


def _classify_status(value: float, min_val: Optional[float], max_val: Optional[float]) -> Optional[str]:
    if min_val is not None and value < min_val:
        return "baixo"
    if max_val is not None and value > max_val:
        return "alto"
    return None


def _apply_reference_overrides_to_exams(
    exams: list[dict[str, Any]],
    *,
    gender: Optional[str],
    reference_table: dict,
) -> None:
    if not exams or not reference_table:
        return
    reference_index = _build_reference_index(reference_table)
    for entry in exams:
        name = entry.get("nome") or entry.get("name") or entry.get("test")
        if not name:
            continue
        ref_entry = _match_reference_entry(name, reference_index)
        reference_value = None
        if ref_entry:
            reference_value = ref_entry.get("ideal")
        if not reference_value:
            reference_value = entry.get("referencia") or entry.get("reference")
        if reference_value:
            entry["reference_display"] = _format_reference_label(reference_value, gender)
        value = _coerce_float(entry.get("valor") or entry.get("value"))
        if value is None or reference_value is None:
            continue
        min_val, max_val = _parse_reference_bounds(reference_value, gender)
        if min_val is None and max_val is None:
            continue
        entry["status"] = _classify_status(value, min_val, max_val) or "normal"


def _apply_reference_rules(analysis: dict[str, Any], reference_table: dict) -> tuple[list[dict[str, Any]], list[str]]:
    exams = analysis.get("exames") or []
    patient = analysis.get("paciente") or {}
    gender = _normalize_gender_label(patient.get("sexo"))
    reference_index = _build_reference_index(reference_table)
    filtered_exams: list[dict[str, Any]] = []
    prescription: list[str] = []
    seen_meds: set[str] = set()

    for exam in exams:
        name = exam.get("nome") or exam.get("name") or exam.get("test")
        if not name:
            continue
        entry = _match_reference_entry(name, reference_index)
        if not entry:
            continue
        value = _coerce_float(exam.get("valor") or exam.get("value"))
        if value is None:
            continue
        min_val, max_val = _parse_reference_bounds(entry.get("ideal"), gender)
        status = _classify_status(value, min_val, max_val)
        if status not in {"baixo", "alto"}:
            continue
        filtered_exams.append({
            "nome": name,
            "valor": value,
            "referencia": entry.get("ideal"),
            "status": status,
        })

        meds_payload = entry.get("medications") if isinstance(entry.get("medications"), dict) else {}
        med_candidates = meds_payload.get("low" if status == "baixo" else "high") or []
        if isinstance(med_candidates, dict):
            med_iterable = [med_candidates]
        elif isinstance(med_candidates, list):
            med_iterable = med_candidates
        else:
            med_iterable = []
        for med in med_iterable:
            if not isinstance(med, dict):
                continue
            parts = [med.get("nome")]
            applic = med.get("aplicacao") or med.get("aplicação")
            if applic:
                parts.append(applic)
            prep = med.get("preparo")
            if prep:
                parts.append(prep)
            text = " — ".join(part for part in parts if part)
            if text and text not in seen_meds:
                prescription.append(text)
                seen_meds.add(text)

    return filtered_exams, prescription


def _format_reference_label(reference_value: Any, gender: Optional[str]) -> str:
    if isinstance(reference_value, str):
        return reference_value
    if isinstance(reference_value, dict):
        if gender:
            first = gender[:1].upper()
            for key in (gender, first):
                if key in reference_value:
                    return reference_value[key]
        return "; ".join(f"{k}: {v}" for k, v in reference_value.items())
    if isinstance(reference_value, list):
        return " / ".join(str(item) for item in reference_value if item)
    return ""
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
    return serve_react_index()


@app.route('/api/patient_result/<int:patient_id>')
@login_required
def api_patient_result(patient_id):
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
    else:
        diagnosis = notes.strip() if notes else ""

    patient_payload = {
        "id": patient.id,
        "name": patient.name,
        "birthdate": patient.birthdate.strftime("%d/%m/%Y") if patient.birthdate else "",
        "sex": patient.sex,
        "cpf": patient.cpf,
        "phone_primary": patient.phone_primary,
        "phone_secondary": patient.phone_secondary,
    }

    return jsonify({
        "mode": "classic",
        "patient": patient_payload,
        "diagnosis": diagnosis,
        "prescription": prescription,
        "download_pdf_url": url_for('download_pdf', patient_id=patient.id),
    })

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
        logo_url = f"{base}/static/images/2.png"
    elif request:
        logo_url = url_for("static", filename="images/2.png", _external=True)
    else:
        logo_url = os.path.join(current_app.root_path, "static", "images", "2.png")
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


@app.route('/lab_analysis/pdf', methods=['POST'])
@login_required
def lab_analysis_pdf():
    """Gera PDF apenas com alterações relevantes e a prescrição recomendada."""
    token = request.form.get("token")
    if not token:
        abort(400)
    serializer = URLSafeSerializer(app.config['SECRET_KEY'], salt="lab-analysis-pdf")
    try:
        payload = serializer.loads(token)
    except BadSignature:
        abort(403)

    patient = payload.get("patient") or {}
    exams = payload.get("abnormal_exams") or payload.get("exams") or []
    prescription_raw = payload.get("prescription") or []
    orientations_raw = payload.get("orientations") or []
    summary_text = payload.get("summary") or ""
    doctor_name = payload.get("doctor_name") or (getattr(current_user(), "name", None) or current_user().username)

    patient_override = _parse_json_payload(request.form.get("patient_override"))
    if isinstance(patient_override, dict):
        for key in ("nome", "data_nascimento", "cpf", "sexo", "telefone"):
            value = patient_override.get(key)
            if value:
                patient[key] = value

    summary_override = request.form.get("summary_override")
    if summary_override is not None:
        summary_text = summary_override

    prescription_override = _parse_json_payload(request.form.get("prescription_override"))
    if isinstance(prescription_override, list):
        prescription_raw = [str(item).strip() for item in prescription_override if str(item).strip()]

    orientations_override = _parse_json_payload(request.form.get("orientations_override"))
    if isinstance(orientations_override, list):
        orientations_raw = [str(item).strip() for item in orientations_override if str(item).strip()]

    excluded_prescription_indexes = _parse_index_payload(request.form.get("excluded_prescriptions"))
    excluded_orientation_indexes = _parse_index_payload(request.form.get("excluded_orientations"))

    prescription = _filter_excluded_items(list(prescription_raw), excluded_prescription_indexes)
    orientations = _filter_excluded_items(list(orientations_raw), excluded_orientation_indexes)

    abnormal = [entry for entry in exams if _is_abnormal_result(entry)]
    if not abnormal:
        abnormal = exams

    from weasyprint import HTML

    lines = []
    if patient.get("nome"):
        lines.append(f"Nome: {patient.get('nome')}")
    if patient.get("data_nascimento"):
        lines.append(f"Data de nascimento: {patient.get('data_nascimento')}")
    if patient.get("cpf"):
        lines.append(f"CPF: {patient.get('cpf')}")
    lines.append(f"Médico responsável: {doctor_name}")
    patient_info = "\n".join(lines)

    logo_url = _resolve_public_logo_url("ponzapdf.png")

    pdf_html = render_template(
        "lab_analysis_pdf.html",
        patient_info=patient_info,
        exams=abnormal,
        prescription=prescription,
        orientations=orientations,
        summary=summary_text,
        generated_at=datetime.utcnow(),
        logo_url=logo_url,
    )

    pdf_io = io.BytesIO()
    HTML(string=pdf_html, base_url=current_app.root_path).write_pdf(pdf_io)
    pdf_io.seek(0)

    filename = f"Analise_{(patient.get('nome') or 'Paciente').replace(' ', '_')}.pdf"
    return send_file(
        pdf_io,
        as_attachment=True,
        download_name=filename,
        mimetype="application/pdf",
    )


@app.route('/lab_analysis/view')
@login_required
def lab_analysis_view():
    return serve_react_index()

@app.route('/lab_analysis/loading')
@login_required
def lab_analysis_loading():
    return serve_react_index()


@app.route('/api/lab_analysis/view')
@login_required
def api_lab_analysis_view():
    token = request.args.get("token")
    if not token:
        return jsonify({"success": False, "error": "Token ausente."}), 400
    serializer = URLSafeSerializer(app.config['SECRET_KEY'], salt="lab-analysis-pdf")
    try:
        payload = serializer.loads(token)
    except BadSignature:
        abort(403)

    doctor_name = payload.get("doctor_name") or (getattr(current_user(), "name", None) or current_user().username)
    analysis = {
        "paciente": payload.get("patient") or {},
        "exames": payload.get("exams") or [],
        "abnormal_exams": payload.get("abnormal_exams") or [],
        "resumo_clinico": payload.get("summary") or "",
        "prescricao": payload.get("prescription") or [],
        "orientações": payload.get("orientations") or [],
        "alertas": payload.get("alerts") or [],
    }
    context = _build_analysis_context(
        analysis,
        file_name=payload.get("file_name") or "",
        doctor_name=doctor_name,
    )
    patient_details = [
        {"label": label, "value": value} for label, value in (context.get("patient_details") or [])
    ]
    
    # Include comparison data if available
    has_comparison = payload.get("has_comparison", False)
    comparison_data = {}
    if has_comparison:
        comparison_data = {
            "has_comparison": True,
            "previous_exam_date": payload.get("previous_exam_date"),
            "comparacao_exames": payload.get("comparacao_exames") or [],
            "evolucao_clinica": payload.get("evolucao_clinica") or "",
        }
    
    return jsonify({
        "mode": "ai",
        "patient": context.get("patient") or {},
        "patient_details": patient_details,
        "summary": context.get("summary") or "",
        "exams": context.get("exams") or [],
        "prescription": context.get("prescription") or [],
        "orientations": context.get("orientations") or [],
        "alerts": context.get("alerts") or [],
        "pdf_token": token,
        "doctor_name": doctor_name,
        **comparison_data,
    })

@app.route('/public_download')
def public_download():
    token = request.args.get('token')
    if not token:
        abort(400)
    try:
        s = URLSafeSerializer(app.config['SECRET_KEY'])
        payload = s.loads(token)
    except Exception:
        abort(403)

    if isinstance(payload, dict):
        patient_id = payload.get("patient_id") or payload.get("pid")
        kind = payload.get("kind")
    else:
        patient_id = payload
        kind = None

    if not patient_id:
        abort(403)

    query = PdfFile.query.filter_by(patient_id=patient_id)
    if kind:
        query = query.join(SecureFile).filter(SecureFile.kind == kind)
    pdf = query.order_by(PdfFile.id.desc()).first()
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


@app.route('/api/patient/<int:patient_id>/exam_history')
@login_required
def api_patient_exam_history(patient_id: int):
    """
    Get the exam history for a patient, showing evolution over time.
    Returns list of past exams with their resumo_clinico and abnormal values.
    """
    u = current_user()
    patient = Patient.query.get_or_404(patient_id)
    if patient.user_id != u.id:
        abort(403)
    
    # Get all exam history records ordered by date (most recent first)
    history_records = (
        PatientExamHistory.query
        .filter_by(user_id=u.id, patient_id=patient_id)
        .order_by(PatientExamHistory.exam_date.desc(), PatientExamHistory.created_at.desc())
        .all()
    )
    
    history_list = []
    for record in history_records:
        try:
            abnormal = json.loads(record.abnormal_results) if record.abnormal_results else []
        except (json.JSONDecodeError, TypeError):
            abnormal = []
        
        try:
            all_results = json.loads(record.all_results) if record.all_results else []
        except (json.JSONDecodeError, TypeError):
            all_results = []
        
        history_list.append({
            "id": record.id,
            "exam_date": record.exam_date.isoformat() if record.exam_date else None,
            "resumo_clinico": record.resumo_clinico or "",
            "abnormal_results": abnormal,
            "total_exams": len(all_results),
            "abnormal_count": len(abnormal),
            "created_at": record.created_at.isoformat() if record.created_at else None,
        })
    
    return jsonify({
        "success": True,
        "patient_id": patient_id,
        "patient_name": patient.name,
        "exam_count": len(history_list),
        "history": history_list,
    })


@app.route('/api/patient/<int:patient_id>/exam_history/<int:history_id>')
@login_required
def api_patient_exam_history_detail(patient_id: int, history_id: int):
    """
    Get detailed exam results from a specific history record.
    """
    u = current_user()
    patient = Patient.query.get_or_404(patient_id)
    if patient.user_id != u.id:
        abort(403)
    
    record = PatientExamHistory.query.get_or_404(history_id)
    if record.patient_id != patient_id or record.user_id != u.id:
        abort(403)
    
    try:
        abnormal = json.loads(record.abnormal_results) if record.abnormal_results else []
    except (json.JSONDecodeError, TypeError):
        abnormal = []
    
    try:
        all_results = json.loads(record.all_results) if record.all_results else []
    except (json.JSONDecodeError, TypeError):
        all_results = []
    
    return jsonify({
        "success": True,
        "id": record.id,
        "patient_id": patient_id,
        "exam_date": record.exam_date.isoformat() if record.exam_date else None,
        "resumo_clinico": record.resumo_clinico or "",
        "abnormal_results": abnormal,
        "all_results": all_results,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    })


@app.route('/result/<int:patient_id>')
@login_required
def result(patient_id):
    """Alias compatível para patient_result (mantém links antigos funcionando)."""
    return redirect(url_for('patient_result', patient_id=patient_id))

# ------------------------------------------------------------------------------
# Agenda (tela)
# ------------------------------------------------------------------------------
def build_agenda_snapshot(user: 'User') -> dict[str, Any]:
    now = datetime.utcnow()
    today_start = datetime(now.year, now.month, now.day)
    tomorrow_start = today_start + timedelta(days=1)
    week_start = today_start - timedelta(days=today_start.weekday())
    week_end = week_start + timedelta(days=7)
    next_window_end = now + timedelta(days=7)

    base_query = AgendaEvent.query.filter(AgendaEvent.user_id == user.id)

    summary = {
        "today_count": base_query.filter(AgendaEvent.start >= today_start, AgendaEvent.start < tomorrow_start).count(),
        "week_count": base_query.filter(AgendaEvent.start >= week_start, AgendaEvent.start < week_end).count(),
        "returns_count": base_query.filter(AgendaEvent.start >= week_start, AgendaEvent.start < week_end, func.lower(AgendaEvent.type) == 'retorno').count(),
        "blocked_count": base_query.filter(AgendaEvent.start >= week_start, AgendaEvent.start < week_end, func.lower(AgendaEvent.type) == 'bloqueio').count(),
        "upcoming_count": base_query.filter(AgendaEvent.start >= now, AgendaEvent.start < next_window_end).count(),
    }

    upcoming_events = (
        AgendaEvent.query.filter(
            AgendaEvent.user_id == user.id,
            AgendaEvent.start >= now
        )
        .order_by(AgendaEvent.start.asc())
        .all()
    )

    def _format_event(ev: AgendaEvent) -> dict[str, Any]:
        start_dt = getattr(ev, "start", None)
        start_iso = start_dt.isoformat() if start_dt else ""
        start_label = start_dt.strftime("%d/%m %H:%M") if start_dt else "--"
        weekday = start_dt.strftime("%a").title() if start_dt else ""
        type_slug = (ev.type or 'consulta').lower()
        billing_slug = (ev.billing or 'particular').lower()
        type_labels = {
            'consulta': 'Consulta',
            'retorno': 'Retorno',
            'procedimento': 'Procedimento',
            'bloqueio': 'Bloqueio',
        }
        billing_labels = {
            'particular': 'Particular',
            'convênio': 'Convênio',
            'convenio': 'Convênio',
        }
        return {
            "id": ev.id,
            "title": ev.title or "Evento",
            "start_iso": start_iso,
            "start_label": start_label,
            "weekday": weekday,
            "type_slug": type_slug,
            "type_label": type_labels.get(type_slug, type_slug.title()),
            "billing_label": billing_labels.get(billing_slug, billing_slug.title()),
            "notes": (ev.notes or ""),
            "phone": (ev.phone or ""),
        }

    upcoming_payload = [_format_event(ev) for ev in upcoming_events]

    type_counts_raw = (
        db.session.query(func.coalesce(func.lower(AgendaEvent.type), 'consulta'), func.count())
        .filter(AgendaEvent.user_id == user.id)
        .group_by(func.coalesce(func.lower(AgendaEvent.type), 'consulta'))
        .all()
    )
    type_total = sum(count for _, count in type_counts_raw) or 1
    type_summary = []
    for slug, count in type_counts_raw:
        label_map = {
            'consulta': 'Consultas',
            'retorno': 'Retornos',
            'procedimento': 'Procedimentos',
            'bloqueio': 'Bloqueios',
        }
        type_summary.append({
            "slug": slug,
            "label": label_map.get(slug, slug.title()),
            "count": count,
            "percent": round((count / type_total) * 100),
        })
    type_summary.sort(key=lambda item: item["count"], reverse=True)

    waitlist_count = WaitlistItem.query.filter(WaitlistItem.user_id == user.id).count()

    return {
        "summary": summary,
        "upcoming_events": upcoming_payload,
        "type_summary": type_summary,
        "waitlist_count": waitlist_count,
    }


@app.route('/agenda', methods=['GET'], endpoint='agenda')
@login_required
def agenda_view():
    return serve_react_index()


@app.route('/api/agenda_snapshot', methods=['GET'])
@login_required
def api_agenda_snapshot():
    snapshot = build_agenda_snapshot(current_user())
    return _jsonify_with_cache(snapshot, max_age=60, stale_while_revalidate=120)

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


def _coerce_to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "on", "yes", "sim"}
    return bool(value)


def _apply_private_cache_headers(response, *, max_age: int = 60, stale_while_revalidate: int = 120):
    response.headers["Cache-Control"] = (
        f"private, max-age={max_age}, stale-while-revalidate={stale_while_revalidate}"
    )
    response.headers["Vary"] = "Cookie"
    return response


def _jsonify_with_cache(payload, *, max_age: int = 60, stale_while_revalidate: int = 120):
    response = jsonify(payload)
    etag = hashlib.sha256(response.get_data()).hexdigest()
    if request.if_none_match and etag in request.if_none_match:
        not_modified = current_app.response_class(status=304)
        not_modified.set_etag(etag)
        return _apply_private_cache_headers(
            not_modified,
            max_age=max_age,
            stale_while_revalidate=stale_while_revalidate,
        )
    response.set_etag(etag)
    return _apply_private_cache_headers(
        response,
        max_age=max_age,
        stale_while_revalidate=stale_while_revalidate,
    )


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

    types_param = (request.args.get('types') or '').strip()
    if types_param:
        type_values = [t.strip().lower() for t in types_param.split(',') if t.strip()]
        if type_values:
            q = q.filter(func.lower(AgendaEvent.type).in_(type_values))

    search_term = (request.args.get('search') or '').strip()
    if search_term:
        like_pattern = f"%{search_term}%"
        q = q.filter(or_(
            AgendaEvent.title.ilike(like_pattern),
            AgendaEvent.notes.ilike(like_pattern),
            AgendaEvent.insurer.ilike(like_pattern),
            AgendaEvent.billing.ilike(like_pattern)
        ))

    events: list[dict[str, Any]] = []

    # Eventos da Agenda
    for e in q.all():
        type_slug = (getattr(e, "type", "") or "consulta").lower()
        class_names = []
        if type_slug == "bloqueio":
            class_names.append("holiday-event")
        class_names.append(f"event-type-{type_slug}")
        events.append({
            "id": getattr(e, "id", None),
            "title": e.title or "Evento",
            "start": e.start.isoformat() if e.start else None,
            "end":   e.end.isoformat()   if e.end   else None,
            "allDay": False,
            "className": " ".join(class_names),
            "extendedProps": {
                "notes": getattr(e, "notes", None),
                "type": getattr(e, "type", None),
                "billing": getattr(e, "billing", None),
                "insurer": getattr(e, "insurer", None),
                "phone": getattr(e, "phone", None),
                "send_reminders": bool(getattr(e, "send_reminders", False)),
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
    send_reminders = _coerce_to_bool(data.get('send_reminders'))

    if type_ == 'bloqueio':
        send_reminders = False

    if not title or not start_s:
        return jsonify(success=False, error="Título e data/hora são obrigatórios."), 400

    start_dt = _parse_iso_to_naive_utc(start_s)
    if not start_dt:
        return jsonify(success=False, error="Formato de data/hora inválido (start)."), 400

    end_dt = _parse_iso_to_naive_utc(end_s) if end_s else start_dt + timedelta(hours=1)
    if end_s and not end_dt:
        return jsonify(success=False, error="Formato de data/hora inválido (end)."), 400
    if end_dt and end_dt <= start_dt:
        end_dt = end_dt + timedelta(days=1)

    ev = AgendaEvent(
        user_id=u.id,
        title=title,
        phone=phone,
        start=start_dt,
        end=end_dt,
        notes=notes or None,
        type=type_ or None,
        billing=billing or None,
        insurer=insurer or None,
        send_reminders=send_reminders,
    )
    db.session.add(ev)
    db.session.commit()

    if send_reminders:
        _schedule_event_reminders(u, ev, include_created=True)

    return jsonify(success=True, event_id=ev.id), 201

scheduler = BackgroundScheduler()
scheduler.start()

def schedule_whatsapp_job(func, run_at, kwargs, *, job_id: Optional[str] = None):
    """Agenda o envio de mensagens no horário correto."""
    if run_at is None:
        return
    now = datetime.now()
    if run_at <= now:
        run_at = now + timedelta(minutes=1)
    scheduler.add_job(
        func,
        'date',
        run_date=run_at,
        kwargs=kwargs,
        id=job_id,
        replace_existing=True,
    )


def _schedule_clinic_summary_job(user: 'User', event_start: datetime) -> None:
    """Programa o envio diário consolidado para a clínica."""
    if not user or not getattr(user, "clinic_phone", None):
        return
    if not event_start:
        return

    summary_date = event_start.date()
    job_id = f"clinic_summary_{user.id}_{summary_date.isoformat()}"
    if scheduler.get_job(job_id):
        return

    run_at = datetime(
        summary_date.year,
        summary_date.month,
        summary_date.day,
        8,
        0,
        0,
    )
    now = datetime.now()
    if run_at <= now:
        run_at = now + timedelta(minutes=1)

    scheduler.add_job(
        _send_clinic_summary_job,
        'date',
        run_date=run_at,
        kwargs={"user_id": user.id, "summary_date": summary_date.isoformat()},
        id=job_id,
        replace_existing=True,
    )


def _send_clinic_summary_job(user_id: int, summary_date: str) -> None:
    """Envia um resumo com todos os pacientes do dia para a clínica."""
    with app.app_context():
        user = User.query.get(user_id)
        if not user or not user.clinic_phone:
            return

        try:
            target_date = datetime.fromisoformat(summary_date).date()
        except ValueError:
            target_date = datetime.now().date()

        day_start = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0)
        day_end = day_start + timedelta(days=1)

        events = (
            AgendaEvent.query
            .filter(
                AgendaEvent.user_id == user.id,
                AgendaEvent.start >= day_start,
                AgendaEvent.start < day_end,
                AgendaEvent.send_reminders.is_(True),
            )
            .order_by(AgendaEvent.start.asc())
            .all()
        )

        appointments = [
            ev for ev in events if (ev.type or "").lower() != "bloqueio"
        ]
        if not appointments:
            return

        clinic_name = user.name or user.username or "Clínica"
        date_str = target_date.strftime("%d/%m/%Y")
        lines = [
            f"Bom dia, {clinic_name}!",
            f"Pacientes do dia {date_str}:",
        ]
        for ev in appointments:
            start_label = ev.start.strftime("%H:%M") if ev.start else "--:--"
            end_label = ev.end.strftime("%H:%M") if ev.end else ""
            patient_name = ev.title or "Paciente"
            phone_label = f" ({ev.phone})" if ev.phone else ""
            time_block = f"{start_label}{f' - {end_label}' if end_label else ''}"
            lines.append(f"• {time_block} — {patient_name}{phone_label}")

        message = "\n".join(lines)
        send_text(user.clinic_phone, message)


def _remove_event_reminders(event_id: int) -> None:
    for suffix in ("created", "one_hour"):
        job_id = f"agenda_{event_id}_{suffix}"
        job = scheduler.get_job(job_id)
        if job:
            scheduler.remove_job(job_id)


def _schedule_event_reminders(user: 'User', event: AgendaEvent, *, include_created: bool) -> None:
    if not getattr(event, "send_reminders", False):
        return
    start_dt = getattr(event, "start", None)
    if not start_dt:
        return

    end_dt = getattr(event, "end", None) or (start_dt + timedelta(hours=1))
    clinic_name = user.username or user.name or "Clínica"
    patient_name = event.title or "Paciente"

    date_str = start_dt.strftime("%d/%m/%Y")
    time_start = start_dt.strftime("%H:%M")
    time_end = end_dt.strftime("%H:%M") if end_dt else time_start

    _schedule_clinic_summary_job(user, start_dt)

    patient_phone = getattr(event, "phone", None)
    if patient_phone:
        if include_created:
            schedule_whatsapp_job(
                func=send_reminder_patient,
                run_at=datetime.now(),
                kwargs={
                    "patient_phone": patient_phone,
                    "patient_name": patient_name,
                    "clinic_name": clinic_name,
                    "date_str": date_str,
                    "time_start": time_start,
                    "time_end": time_end,
                },
                job_id=f"agenda_{event.id}_created",
            )

        one_hour_before = start_dt - timedelta(hours=1)
        if one_hour_before > datetime.now():
            schedule_whatsapp_job(
                func=send_reminder_patient,
                run_at=one_hour_before,
                kwargs={
                    "patient_phone": patient_phone,
                    "patient_name": patient_name,
                    "clinic_name": clinic_name,
                    "date_str": date_str,
                    "time_start": time_start,
                    "time_end": time_end,
                },
                job_id=f"agenda_{event.id}_one_hour",
            )

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
        _remove_event_reminders(event_id)
        db.session.delete(ev)
        db.session.commit()
        return jsonify(success=True)

    data = request.get_json(silent=True) or {}
    should_schedule = False

    if 'start' in data:
        start_dt = _parse_iso_to_naive_utc((data.get('start') or '').strip())
        if not start_dt:
            return jsonify(success=False, error="Formato de data/hora inválido para 'start'."), 400
        ev.start = start_dt
        should_schedule = True

    if 'end' in data:
        end_val = (data.get('end') or '').strip()
        if end_val:
            end_dt = _parse_iso_to_naive_utc(end_val)
            if not end_dt:
                return jsonify(success=False, error="Formato de data/hora inválido para 'end'."), 400
            if end_dt <= ev.start:
                end_dt = end_dt + timedelta(days=1)
            ev.end = end_dt
        else:
            ev.end = None

    if 'send_reminders' in data:
        ev.send_reminders = _coerce_to_bool(data.get('send_reminders'))
        should_schedule = should_schedule or ev.send_reminders

    for key in ('title', 'notes', 'type', 'billing', 'insurer', 'phone'):
        if key in data:
            value = (data.get(key) or '').strip()
            setattr(ev, key, (value or None))
            if key in ('title', 'phone') and ev.send_reminders:
                should_schedule = True

    if (ev.type or '').lower() == 'bloqueio':
        ev.send_reminders = False

    db.session.commit()

    if not ev.send_reminders:
        _remove_event_reminders(event_id)
    elif should_schedule:
        _schedule_event_reminders(u, ev, include_created=False)

    return jsonify(success=True)

# ------------------------------------------------------------------------------
# Catálogo / Pacientes
# ------------------------------------------------------------------------------
def _normalize_birthdate_input(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    only_digits = re.sub(r'\D', '', raw)
    if len(only_digits) == 8:
        raw = f"{only_digits[:2]}/{only_digits[2:4]}/{only_digits[4:]}"
    return _parse_birthdate(raw)

def _resolve_patient_image(path: Optional[str]) -> str:
    if not path:
        return url_for('static', filename='images/user-icon.png')
    if path.startswith(('/static/', '/files/')):
        return path
    if path.startswith('/uploads/'):
        return f"/static{path}"
    if path.startswith('uploads/'):
        return f"/static/{path}"
    if path.startswith('images/'):
        return url_for('static', filename=path)
    return path

def _serialize_patient_summary(patient: Patient) -> dict:
    # Get exam count efficiently using the relationship
    exam_count = patient.exam_history.count() if hasattr(patient, 'exam_history') else 0
    return {
        "id": patient.id,
        "name": patient.name,
        "phone_primary": patient.phone_primary or "",
        "doctor_name": patient.doctor.name if patient.doctor else "",
        "status": patient.status or "Inativo",
        "profile_image": _resolve_patient_image(patient.profile_image),
        "exam_count": exam_count,
    }

def _serialize_patient_detail(patient: Patient) -> dict:
    return {
        "id": patient.id,
        "name": patient.name or "",
        "birthdate": patient.birthdate.strftime("%d/%m/%Y") if patient.birthdate else "",
        "sex": patient.sex or "",
        "email": patient.email or "",
        "cpf": patient.cpf or "",
        "marital_status": patient.marital_status or "",
        "father_name": patient.father_name or "",
        "mother_name": patient.mother_name or "",
        "phone_primary": patient.phone_primary or "",
        "phone_secondary": patient.phone_secondary or "",
        "education_level": patient.education_level or "",
        "profession": patient.profession or "",
        "monthly_income": patient.monthly_income or "",
        "special_needs": patient.special_needs or "",
        "chronic_conditions": patient.chronic_conditions or "",
        "emergency_contact_name": patient.emergency_contact_name or "",
        "emergency_contact_phone": patient.emergency_contact_phone or "",
        "has_health_plan": bool(patient.has_health_plan),
        "notes": patient.notes or "",
        "cep": patient.address_cep or "",
        "street": patient.address_street or "",
        "number": patient.address_number or "",
        "complement": patient.address_complement or "",
        "district": patient.address_district or "",
        "city": patient.address_city or "",
        "state": patient.address_state or "",
        "profile_image": _resolve_patient_image(patient.profile_image),
    }

@app.route('/api/patients', methods=['GET', 'POST'])
@login_required
def api_patients():
    u = current_user()

    if request.method == 'GET':
        search = (request.args.get('search') or '').strip().lower()
        status = (request.args.get('status') or '').strip()

        patients = Patient.query.filter_by(user_id=u.id).all()
        if search:
            patients = [p for p in patients if search in (p.name or '').lower()]
        if status:
            patients = [p for p in patients if (p.status or '') == status]

        payload = {
            "patients": [_serialize_patient_summary(p) for p in patients],
            "total": len(patients),
        }
        return _jsonify_with_cache(payload, max_age=60, stale_while_revalidate=120)

    data = request.form if not request.is_json else (request.get_json(silent=True) or {})
    default_image_url = url_for('static', filename='images/user-icon.png')

    name = (data.get('name') or '').strip()
    birthdate_raw = (data.get('birthdate') or '').strip()
    birthdate = _normalize_birthdate_input(birthdate_raw)
    sex = (data.get('sex') or '').strip()
    email = (data.get('email') or '').strip().lower()
    cpf = (data.get('cpf') or data.get('document') or '').strip().replace('.', '').replace('-', '')
    marital_status = (data.get('marital_status') or '').strip()
    father_name = (data.get('father_name') or '').strip()
    mother_name = (data.get('mother_name') or '').strip()
    education_level = (data.get('education_level') or '').strip()
    profession = (data.get('profession') or '').strip()
    monthly_income = (data.get('monthly_income') or '').strip()
    special_needs = (data.get('special_needs') or '').strip()
    chronic_conditions = (data.get('chronic_conditions') or '').strip()
    emergency_contact_name = (data.get('emergency_contact_name') or '').strip()
    emergency_contact_phone = (data.get('emergency_contact_phone') or '').strip()
    has_health_plan = _coerce_to_bool(data.get('has_health_plan'))
    notes = (data.get('notes') or '').strip()
    phone_pri = (data.get('phone_primary') or data.get('phone') or '').strip()
    phone_sec = (data.get('phone_secondary') or '').strip()
    cep = (data.get('cep') or data.get('zipcode') or '').strip()
    street = (data.get('street') or '').strip()
    number = (data.get('number') or '').strip()
    complement = (data.get('complement') or '').strip()
    district = (data.get('district') or '').strip()
    city = (data.get('city') or '').strip()
    state = (data.get('state') or '').strip().upper()

    missing = []
    if not name:
        missing.append("name")
    if not birthdate:
        missing.append("birthdate")
    if not sex:
        missing.append("sex")
    if not phone_pri:
        missing.append("phone_primary")

    if missing:
        return jsonify(success=False, error="Preencha todos os campos obrigatorios."), 400
    if email and not basic_email(email):
        return jsonify(success=False, error="E-mail inválido."), 400

    profile_rel = default_image_url
    file = request.files.get('profile_image')
    if file and file.filename:
        if allowed_file(file.filename):
            filename = secure_filename(file.filename)
            ext = filename.rsplit('.', 1)[1].lower()
            dest_dir = os.path.join(STATIC_DIR, "uploads", "patients")
            os.makedirs(dest_dir, exist_ok=True)
            new_name = f"patient_{u.id}_{int(time.time())}.{ext}"
            dest_path = os.path.join(dest_dir, new_name)
            file.save(dest_path)
            profile_rel = "/" + os.path.relpath(dest_path, STATIC_DIR).replace("\\", "/")
        else:
            return jsonify(success=False, error="Tipo de arquivo não permitido."), 400

    p = Patient(
        user_id=u.id,
        name=name,
        birthdate=birthdate,
        sex=sex or None,
        email=email or None,
        cpf=cpf or None,
        marital_status=marital_status or None,
        father_name=father_name or None,
        mother_name=mother_name or None,
        education_level=education_level or None,
        profession=profession or None,
        monthly_income=monthly_income or None,
        special_needs=special_needs or None,
        chronic_conditions=chronic_conditions or None,
        emergency_contact_name=emergency_contact_name or None,
        emergency_contact_phone=emergency_contact_phone or None,
        has_health_plan=has_health_plan,
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
    return jsonify(success=True, patient_id=p.id), 201

@app.route('/api/patients/<int:patient_id>', methods=['GET', 'POST', 'PUT'])
@login_required
def api_patient_detail(patient_id: int):
    u = current_user()
    patient = Patient.query.get_or_404(patient_id)
    if patient.user_id != u.id:
        abort(403)

    if request.method == 'GET':
        return jsonify(success=True, patient=_serialize_patient_detail(patient))

    data = request.form if not request.is_json else (request.get_json(silent=True) or {})

    name = (data.get('name') or '').strip()
    if not name:
        return jsonify(success=False, error="Informe o nome do paciente."), 400

    birthdate_raw = (data.get('birthdate') or '').strip()
    birthdate = _normalize_birthdate_input(birthdate_raw) if birthdate_raw else None
    sex = (data.get('sex') or '').strip()
    email = (data.get('email') or '').strip().lower()
    cpf = (data.get('cpf') or data.get('document') or '').strip().replace('.', '').replace('-', '')
    marital_status = (data.get('marital_status') or '').strip()
    father_name = (data.get('father_name') or '').strip()
    mother_name = (data.get('mother_name') or '').strip()
    education_level = (data.get('education_level') or '').strip()
    profession = (data.get('profession') or '').strip()
    monthly_income = (data.get('monthly_income') or '').strip()
    special_needs = (data.get('special_needs') or '').strip()
    chronic_conditions = (data.get('chronic_conditions') or '').strip()
    emergency_contact_name = (data.get('emergency_contact_name') or '').strip()
    emergency_contact_phone = (data.get('emergency_contact_phone') or '').strip()
    has_health_plan = _coerce_to_bool(data.get('has_health_plan'))
    notes = (data.get('notes') or '').strip()
    phone_pri = (data.get('phone_primary') or data.get('phone') or '').strip()
    phone_sec = (data.get('phone_secondary') or '').strip()
    cep = (data.get('cep') or data.get('zipcode') or '').strip()
    street = (data.get('street') or '').strip()
    number = (data.get('number') or '').strip()
    complement = (data.get('complement') or '').strip()
    district = (data.get('district') or '').strip()
    city = (data.get('city') or '').strip()
    state = (data.get('state') or '').strip().upper()

    if email and not basic_email(email):
        return jsonify(success=False, error="E-mail inválido."), 400

    file = request.files.get('profile_image')
    if file and file.filename:
        if not allowed_file(file.filename):
            return jsonify(success=False, error="Tipo de arquivo não permitido."), 400

        filename = secure_filename(file.filename)
        ext = filename.rsplit('.', 1)[1].lower()
        if ext not in {"png", "jpg", "jpeg"}:
            return jsonify(success=False, error="Tipo de arquivo não permitido."), 400

        content = file.read()
        if not content:
            return jsonify(success=False, error="Arquivo de imagem inválido."), 400

        old_rel = (patient.profile_image or "").replace("\\", "/")
        old_sid = _extract_securefile_id_from_url(old_rel)
        if old_sid:
            _delete_securefile_if_owned(old_sid, u.id)
        else:
            _safe_remove_patient_photo(old_rel)

        new_name = f"patient_{u.id}_{int(time.time())}.{ext}"
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

    patient.name = name
    patient.birthdate = birthdate
    patient.sex = sex or None
    patient.email = email or None
    patient.cpf = cpf or None
    patient.marital_status = marital_status or None
    patient.father_name = father_name or None
    patient.mother_name = mother_name or None
    patient.education_level = education_level or None
    patient.profession = profession or None
    patient.monthly_income = monthly_income or None
    patient.special_needs = special_needs or None
    patient.chronic_conditions = chronic_conditions or None
    patient.emergency_contact_name = emergency_contact_name or None
    patient.emergency_contact_phone = emergency_contact_phone or None
    patient.has_health_plan = has_health_plan
    patient.notes = notes or None
    patient.phone_primary = phone_pri
    patient.phone_secondary = phone_sec or None
    patient.address_cep = cep or None
    patient.address_street = street or None
    patient.address_number = number or None
    patient.address_complement = complement or None
    patient.address_district = district or None
    patient.address_city = city or None
    patient.address_state = state or None

    db.session.commit()
    return jsonify(success=True, patient_id=patient.id)

@app.route('/catalog/register', methods=['GET', 'POST'])
@login_required
def register_patient():
    import time as _time

    u = current_user()

    if request.method == 'GET' and not _request_wants_json():
        return serve_react_index()

    # URL absoluta da imagem padrão (útil para gravar direto no campo profile_image)
    default_image_url = url_for('static', filename='images/user-icon.png')
    wants_json = _request_wants_json()

    def _register_patient_error(message: str, fields: Optional[list[str]] = None):
        if wants_json:
            return jsonify({"success": False, "error": message, "fields": fields or []}), 400
        flash(message, "warning")
        return redirect(url_for('catalog'))

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
        marital_status = (request.form.get('marital_status') or '').strip()
        father_name = (request.form.get('father_name') or '').strip()
        mother_name = (request.form.get('mother_name') or '').strip()
        education_level = (request.form.get('education_level') or '').strip()
        profession = (request.form.get('profession') or '').strip()
        monthly_income = (request.form.get('monthly_income') or '').strip()
        special_needs = (request.form.get('special_needs') or '').strip()
        chronic_conditions = (request.form.get('chronic_conditions') or '').strip()
        emergency_contact_name = (request.form.get('emergency_contact_name') or '').strip()
        emergency_contact_phone = (request.form.get('emergency_contact_phone') or '').strip()
        has_health_plan = _coerce_to_bool(request.form.get('has_health_plan'))
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
            return _register_patient_error("Preencha todos os campos obrigatórios.", missing)

        if email and not basic_email(email):
            return _register_patient_error("E-mail inválido.", ["email"])

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
                return _register_patient_error(
                    "Tipo de arquivo não permitido. Use png, jpg ou jpeg.",
                    ["profile_image"],
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
            marital_status=marital_status or None,
            father_name=father_name or None,
            mother_name=mother_name or None,
            education_level=education_level or None,
            profession=profession or None,
            monthly_income=monthly_income or None,
            special_needs=special_needs or None,
            chronic_conditions=chronic_conditions or None,
            emergency_contact_name=emergency_contact_name or None,
            emergency_contact_phone=emergency_contact_phone or None,
            has_health_plan=has_health_plan,
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

        if wants_json:
            return jsonify({"success": True, "id": p.id, "redirect_url": url_for('catalog')})
        flash('Paciente cadastrado com sucesso.', 'success')
        return redirect(url_for('catalog'))

    # GET
    return serve_react_index()


@app.route('/catalog')
@login_required
def catalog():
    return serve_react_index()

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

    if request.method == 'GET' and not _request_wants_json():
        return serve_react_index()

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
        marital_status = (request.form.get('marital_status') or '').strip()
        father_name = (request.form.get('father_name') or '').strip()
        mother_name = (request.form.get('mother_name') or '').strip()
        education_level = (request.form.get('education_level') or '').strip()
        profession = (request.form.get('profession') or '').strip()
        monthly_income = (request.form.get('monthly_income') or '').strip()
        special_needs = (request.form.get('special_needs') or '').strip()
        chronic_conditions = (request.form.get('chronic_conditions') or '').strip()
        emergency_contact_name = (request.form.get('emergency_contact_name') or '').strip()
        emergency_contact_phone = (request.form.get('emergency_contact_phone') or '').strip()
        has_health_plan = _coerce_to_bool(request.form.get('has_health_plan'))
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
        patient.marital_status     = marital_status or None
        patient.father_name        = father_name or None
        patient.mother_name        = mother_name or None
        patient.education_level    = education_level or None
        patient.profession         = profession or None
        patient.monthly_income     = monthly_income or None
        patient.special_needs      = special_needs or None
        patient.chronic_conditions = chronic_conditions or None
        patient.emergency_contact_name = emergency_contact_name or None
        patient.emergency_contact_phone = emergency_contact_phone or None
        patient.has_health_plan    = has_health_plan
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

    return serve_react_index()

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
    return serve_react_index()


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

    try:
        Consult.query.filter_by(patient_id=patient_id).delete(synchronize_session=False)
        db.session.delete(p)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        message = f'Falha ao remover paciente: {exc}'
        if wants_json_response():
            return jsonify(success=False, message=message), 500
        flash(message, 'warning')
        return redirect(url_for('catalog'))

    if wants_json_response():
        return jsonify(success=True)

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
    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        message = f'Falha ao alterar status: {exc}'
        if wants_json_response():
            return jsonify(success=False, message=message), 500
        flash(message, 'warning')
        return redirect(url_for('catalog'))

    if wants_json_response():
        return jsonify(success=True, status=p.status)

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
    abort(404)

@app.route('/api_doctors')
def api_doctors():
    abort(404)

@app.route('/doctors/add', methods=['POST'], endpoint='add_doctor_route')
@login_required
def add_doctor_route():
    abort(404)

@app.route('/doctors/<int:doctor_id>', methods=['GET', 'POST'], endpoint='doctor_view')
@login_required
def doctor_view(doctor_id):
    abort(404)

@app.route('/doctors/<int:doctor_id>/update', methods=['POST'])
@login_required
def doctor_update(doctor_id):
    abort(404)

@app.route('/doctor/<int:doctor_id>/edit', methods=['GET', 'POST'], endpoint='doctor_edit')
@login_required
def doctor_edit(doctor_id):
    abort(404)

@app.route('/doctor/<int:doctor_id>/delete', methods=['POST'], endpoint='doctor_delete')
@login_required
def doctor_delete(doctor_id):
    abort(404)

# ------------------------------------------------------------------------------
# Cotações / Fornecedores / Produtos
# ------------------------------------------------------------------------------
def _format_dt_br(value: Optional[datetime]) -> Optional[str]:
    if not value:
        return None
    try:
        return value.astimezone(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M")
    except Exception:
        try:
            return value.strftime("%d/%m/%Y %H:%M")
        except Exception:
            return None

def _normalize_quote_items(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str):
        return [ln.strip() for ln in raw.splitlines() if ln.strip()]
    return []

def _load_quote_items(raw_text: Optional[str]) -> list[str]:
    if not raw_text:
        return []
    try:
        parsed = json.loads(raw_text)
        if isinstance(parsed, list):
            return _normalize_quote_items(parsed)
    except Exception:
        pass
    return _normalize_quote_items(raw_text)

def _normalize_quote_answers(raw: Optional[str]) -> list[dict[str, str]]:
    answers = []
    payload: Any = []
    if raw:
        try:
            payload = json.loads(raw)
        except Exception:
            payload = []
    if isinstance(payload, dict) and "answers" in payload:
        payload = payload.get("answers") or []
    if not isinstance(payload, list):
        return answers
    for item in payload:
        if not isinstance(item, dict):
            continue
        price = str(item.get("price", "")).strip()
        deadline = item.get("deadline", "")
        if price:
            try:
                price_val = Decimal(str(price).replace(".", "").replace(",", "."))
                price = f"{price_val:.2f}".replace(".", ",")
            except Exception:
                price = price or ""
        deadline_val = ""
        if deadline is not None and str(deadline).strip():
            try:
                deadline_val = str(int(deadline))
            except Exception:
                deadline_val = str(deadline).strip()
        answers.append({"price": price, "deadline": deadline_val})
    return answers

@app.route('/api/quotes', methods=['GET', 'POST'])
@login_required
def api_quotes():
    u = current_user()
    if request.method == 'GET':
        quotes = Quote.query.filter(Quote.user_id == u.id).order_by(Quote.created_at.desc()).all()
        items = []
        for q in quotes:
            items.append({
                "id": q.id,
                "title": q.title,
                "created_at_br": _format_dt_br(q.created_at),
                "suppliers": [{"id": s.id, "name": s.name} for s in (q.suppliers or [])],
                "responses_count": len(q.responses or []),
            })
        return jsonify({"quotes": items})

    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    raw_items = data.get("items")
    items_list = _normalize_quote_items(raw_items)
    supplier_ids = data.get("supplier_ids") or []

    if not title:
        return jsonify(success=False, error="Informe o nome da cotação."), 400
    if not items_list:
        return jsonify(success=False, error="Informe ao menos um item."), 400

    try:
        supplier_ids = [int(x) for x in supplier_ids if str(x).strip()]
    except Exception:
        supplier_ids = []

    selected_suppliers = []
    if supplier_ids:
        selected_suppliers = Supplier.query.filter(
            Supplier.user_id == u.id,
            Supplier.id.in_(supplier_ids),
        ).all()

    q = Quote(
        user_id=u.id,
        title=title,
        items=json.dumps(items_list, ensure_ascii=False),
    )
    q.suppliers = selected_suppliers  # type: ignore

    db.session.add(q)
    db.session.commit()

    try:
        for s_item in selected_suppliers:
            if not s_item.phone:
                continue
            response_link = _build_supplier_quote_link(q.id, s_item.id)
            wa_err = send_quote_whatsapp(
                supplier_name=s_item.name,
                quote_title=title,
                phone=s_item.phone,
                quote_items=items_list,
                response_url=response_link,
            )
            if wa_err:
                current_app.logger.error(
                    f"[WA] send_quote_whatsapp failed for supplier {s_item.name}: {wa_err}"
                )
    except Exception as e:
        current_app.logger.error(f"[WA] erro no pipeline de envio da cotação: {e}")

    return jsonify(success=True, id=q.id, redirect_url=url_for('quote_view', quote_id=q.id))

@app.route('/api/quotes/<int:quote_id>', methods=['GET'])
@login_required
def api_quote_detail(quote_id: int):
    u = current_user()
    q = Quote.query.get_or_404(quote_id)
    if q.user_id != u.id:
        abort(403)

    items = _load_quote_items(q.items)
    responses_out = []
    for resp in q.responses or []:
        supplier = Supplier.query.get(resp.supplier_id) if resp.supplier_id else None
        supplier_name = supplier.name if supplier else f"Fornecedor #{resp.supplier_id}"
        answers_raw = _normalize_quote_answers(resp.answers)
        answers = []
        for idx, item in enumerate(items):
            if idx >= len(answers_raw):
                break
            entry = answers_raw[idx]
            answers.append({
                "item": item,
                "price": entry.get("price") or "",
                "deadline": entry.get("deadline") or "",
            })
        responses_out.append({
            "supplier": supplier_name,
            "submitted_at": _format_dt_br(resp.submitted_at),
            "answers": answers,
        })

    return jsonify({
        "success": True,
        "quote": {"id": q.id, "title": q.title},
        "items": items,
        "responses": responses_out,
        "meta": {"created_at": _format_dt_br(q.created_at)},
    })

@app.route('/api/quotes/<int:quote_id>/results', methods=['GET'])
@login_required
def api_quote_results(quote_id: int):
    u = current_user()
    q = Quote.query.get_or_404(quote_id)
    if q.user_id != u.id:
        abort(403)

    items = _load_quote_items(q.items)
    suppliers = q.suppliers or []
    supplier_payload = [{"id": s.id, "name": s.name or f"Fornecedor #{s.id}"} for s in suppliers]
    quote_suppliers_ids = [s.id for s in suppliers]

    responses_map: dict[int, list[dict[str, str]]] = {}
    for resp in q.responses or []:
        sid = resp.supplier_id
        if not sid:
            continue
        responses_map[sid] = _normalize_quote_answers(resp.answers)

    best_per_item: dict[int, int] = {}
    for idx in range(len(items)):
        best_sid = None
        best_price = None
        for sid in quote_suppliers_ids:
            answers = responses_map.get(sid) or []
            if idx >= len(answers):
                continue
            price_s = (answers[idx].get("price") or "").strip()
            try:
                price_val = Decimal(price_s.replace(".", "").replace(",", ".")) if price_s else None
            except Exception:
                price_val = None
            if price_val is not None and (best_price is None or price_val < best_price):
                best_price = price_val
                best_sid = sid
        if best_sid is not None:
            best_per_item[idx] = best_sid

    return jsonify({
        "success": True,
        "quote": {"id": q.id, "title": q.title},
        "items": items,
        "suppliers": supplier_payload,
        "responses": responses_map,
        "best_per_item": best_per_item,
    })

@app.route('/quotes', methods=['GET'], endpoint='quote_index')
@login_required
def quote_index():
    return serve_react_index()


@app.route('/quotes/<int:quote_id>/results', methods=['GET'], endpoint='quote_results')
@login_required
def quote_results(quote_id: int):
    return serve_react_index()


def _quote_response_serializer() -> URLSafeTimedSerializer:
    try:
        secret = current_app.config['SECRET_KEY']
    except RuntimeError:
        secret = app.config['SECRET_KEY']
    return URLSafeTimedSerializer(secret, salt="quote-response-link")


def _build_supplier_quote_link(quote_id: int, supplier_id: int) -> str:
    serializer = _quote_response_serializer()
    token = serializer.dumps({"q": quote_id, "s": supplier_id})
    relative_url = url_for('public_quote_response', token=token, _external=False)
    base_url = (
        current_app.config.get("PUBLIC_BASE_URL")
        or current_app.config.get("APP_BASE_URL")
        or os.getenv("PUBLIC_APP_URL")
        or os.getenv("APP_BASE_URL")
    )
    if base_url:
        base = base_url.rstrip('/') + '/'
        return urljoin(base, relative_url.lstrip('/'))
    return url_for('public_quote_response', token=token, _external=True)


@app.route('/quotes/create', methods=['GET', 'POST'], endpoint='create_quote')
@login_required
def create_quote():
    u = current_user()
    if request.method == 'GET' and not _request_wants_json():
        return serve_react_index()
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

        # === ✅ WhatsApp sending with per-supplier signed public link ===
        try:
            for s_item in selected_suppliers:
                if not s_item.phone:
                    continue
                response_link = _build_supplier_quote_link(q.id, s_item.id)
                wa_err = send_quote_whatsapp(
                    supplier_name=s_item.name,
                    quote_title=title,
                    phone=s_item.phone,
                    quote_items=items_list,
                    response_url=response_link,
                )
                if wa_err:
                    current_app.logger.error(
                        f"[WA] send_quote_whatsapp failed for supplier {s_item.name}: {wa_err}"
                    )
        except Exception as e:
            current_app.logger.error(f"[WA] erro no pipeline de envio da cotação: {e}")

        flash('Cotação criada com sucesso!', 'success')
        return redirect(url_for('quote_index'))

    return serve_react_index()


@app.route('/api/quotes/respond/<token>', methods=['GET', 'POST'], endpoint='public_quote_response_api')
def public_quote_response_api(token: str):
    return public_quote_response(token, force_json=True)


@app.route('/quotes/respond/<token>', methods=['GET', 'POST'], endpoint='public_quote_response')
def public_quote_response(token: str, *, force_json: bool = False):
    wants_json = force_json or _request_wants_json()
    if request.method == 'GET' and not wants_json:
        return serve_react_index()

    serializer = _quote_response_serializer()
    max_age = int(os.getenv("QUOTE_RESPONSE_TOKEN_MAX_AGE", 60 * 60 * 24 * 30))
    expired_token = False
    data: Optional[dict[str, Any]] = None
    try:
        decoded = serializer.loads(token, max_age=max_age)
        if isinstance(decoded, dict):
            data = decoded
    except SignatureExpired as exc:
        expired_token = True
        payload = exc.payload if exc.payload is not None else token
        try:
            decoded = serializer.loads(payload)
            if isinstance(decoded, dict):
                data = decoded
        except Exception:
            data = None
    except BadSignature:
        if wants_json:
            return jsonify({"error": "Link inválido."}), 404
        abort(404)

    if not data:
        if wants_json:
            return jsonify({"error": "Link inválido."}), 404
        abort(404)

    quote_id = data.get("q")
    supplier_id = data.get("s")
    if not quote_id or not supplier_id:
        if wants_json:
            return jsonify({"error": "Link inválido."}), 404
        abort(404)

    quote = Quote.query.get_or_404(quote_id)
    supplier = Supplier.query.get_or_404(supplier_id)

    if supplier not in (quote.suppliers or []):
        if wants_json:
            return jsonify({"error": "Acesso negado."}), 403
        abort(403)

    clinic_name = quote.user.name or (quote.user.company.name if quote.user and quote.user.company else None)
    clinic_name = clinic_name or (quote.user.username if quote.user else "")
    clinic_address = getattr(quote.user, "clinic_address", "") if quote.user else ""

    if expired_token:
        if wants_json:
            return jsonify({
                "expired": True,
                "clinic_name": clinic_name,
                "clinic_address": clinic_address,
                "supplier": {
                    "id": supplier.id,
                    "name": supplier.name,
                },
                "items": [],
                "prefill": [],
                "submitted": False,
            }), 410
        return ("", 410)

    try:
        items_raw = json.loads(quote.items or "[]")
        if isinstance(items_raw, list):
            items = [str(x).strip() for x in items_raw if str(x).strip()]
        else:
            items = []
    except Exception:
        items = [ln.strip() for ln in (quote.items or "").splitlines() if ln.strip()]

    response_obj = QuoteResponse.query.filter_by(quote_id=quote.id, supplier_id=supplier.id).first()
    existing_answers: list[dict[str, Any]] = []
    if response_obj and response_obj.answers:
        try:
            payload = json.loads(response_obj.answers)
            if isinstance(payload, list):
                existing_answers = payload
        except Exception:
            existing_answers = []

    prefill: list[dict[str, str]] = []
    for idx in range(len(items)):
        ans = existing_answers[idx] if idx < len(existing_answers) and isinstance(existing_answers[idx], dict) else {}
        prefill.append({
            "price": str(ans.get("price", "")).strip(),
            "deadline": str(ans.get("deadline", "")).strip(),
        })

    submitted = bool(response_obj and response_obj.submitted_at)
    if request.method == 'POST':
        answers_payload: list[dict[str, str]] = []
        if wants_json:
            payload = request.get_json(silent=True) or {}
            answers_input = payload.get("answers")
            if not isinstance(answers_input, list):
                answers_input = []
            for idx, item in enumerate(items):
                answer = answers_input[idx] if idx < len(answers_input) and isinstance(answers_input[idx], dict) else {}
                price_val = str(answer.get("price", "")).strip()
                deadline_val = str(answer.get("deadline", "")).strip()
                answers_payload.append({
                    "item": item,
                    "price": price_val,
                    "deadline": deadline_val,
                })
        else:
            for idx, item in enumerate(items):
                price_val = (request.form.get(f'price_{idx}') or '').strip()
                deadline_val = (request.form.get(f'deadline_{idx}') or '').strip()
                answers_payload.append({
                    "item": item,
                    "price": price_val,
                    "deadline": deadline_val,
                })

        if not answers_payload:
            if wants_json:
                return jsonify({"success": False, "message": "Nenhum item para responder."}), 400
        else:
            if not response_obj:
                response_obj = QuoteResponse(
                    quote_id=quote.id,
                    supplier_id=supplier.id,
                    answers=json.dumps(answers_payload, ensure_ascii=False),
                )
                db.session.add(response_obj)
            else:
                response_obj.answers = json.dumps(answers_payload, ensure_ascii=False)
            response_obj.submitted_at = datetime.utcnow()
            db.session.commit()
            submitted = True

        if wants_json:
            return jsonify({"success": True, "submitted": submitted})

    if wants_json:
        return jsonify({
            "expired": False,
            "clinic_name": clinic_name,
            "clinic_address": clinic_address,
            "supplier": {
                "id": supplier.id,
                "name": supplier.name,
            },
            "items": items,
            "prefill": prefill,
            "submitted": submitted,
        })

    return serve_react_index()


@app.route('/quotes/<int:quote_id>', methods=['GET'], endpoint='quote_view')
@login_required
def quotes_view(quote_id):
    return serve_react_index()


@app.route('/quotes/<int:quote_id>/delete', methods=['POST'], endpoint='quote_delete')
@login_required
def quotes_delete(quote_id):
    u = current_user()
    q = Quote.query.get_or_404(quote_id)
    if q.user_id != u.id:
        abort(403)
    db.session.delete(q)
    db.session.commit()
    prefers_json = (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.accept_mimetypes.best == "application/json"
    )
    if prefers_json:
        return jsonify({"success": True, "message": "Cotação removida."})
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
    return serve_react_index()
    
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
    return serve_react_index()


@app.route('/api/products', methods=['GET', 'POST'])
@login_required
def api_products():
    u = current_user()
    if request.method == 'GET':
        q = Product.query.filter(Product.user_id == u.id)

        search = (request.args.get('search') or '').strip()
        if search:
            like = f"%{search}%"
            q = q.filter(
                or_(
                    func.lower(Product.name).like(func.lower(like)),
                    func.lower(func.coalesce(Product.code, '')).like(func.lower(like))
                )
            )

        status = (request.args.get('status') or '').strip()
        if status in ('Ativo', 'Inativo'):
            q = q.filter(func.trim(Product.status) == status)

        products = q.order_by(Product.created_at.desc()).all()
        return jsonify({
            "products": [{
                "id": p.id,
                "name": p.name,
                "quantity": p.quantity or 0,
                "purchase_price": float(p.purchase_price or 0),
                "sale_price": float(p.sale_price or 0),
                "status": (p.status or 'Inativo').strip() or 'Inativo',
            } for p in products],
            "notifications_unread": 0,
        })

    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    quantity = _to_int(data.get('quantity'), 0)
    purchase_price = float(_to_decimal(data.get('purchase_price')))
    sale_price = float(_to_decimal(data.get('sale_price')))

    if not name:
        return jsonify(success=False, error='Informe o nome do produto.'), 400

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
    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, error=f'Falha ao salvar produto: {e}'), 500

    return jsonify(success=True, product={
        "id": p.id,
        "name": p.name,
        "quantity": p.quantity or 0,
        "purchase_price": float(p.purchase_price or 0),
        "sale_price": float(p.sale_price or 0),
        "status": (p.status or 'Inativo').strip() or 'Inativo',
    }), 201

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
    except Exception as exc:
        db.session.rollback()
        message = f'Falha ao remover: {exc}'
        if wants_json_response() or request.is_json:
            return jsonify(success=False, message=message), 500
        flash(message, 'warning')
        return redirect(url_for('products'))

    if wants_json_response() or request.is_json:
        return jsonify(success=True)

    flash('Produto removido.', 'info')
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
    except Exception as exc:
        db.session.rollback()
        message = f'Falha ao alterar status: {exc}'
        if wants_json_response() or request.is_json:
            return jsonify(success=False, message=message), 500
        flash(message, 'warning')
        return redirect(next_url)

    if wants_json_response() or request.is_json:
        return jsonify(success=True, status=p.status)

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

    prefers_json = (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.accept_mimetypes.best == "application/json"
    )
    data = request.get_json(silent=True) or {}
    name = (data.get('name') if data else request.form.get('name') or '').strip()
    phone = (data.get('phone') if data else request.form.get('phone') or '').strip()
    email = (data.get('email') if data else request.form.get('email') or '').strip()

    if not name:
        if prefers_json:
            return jsonify(success=False, error="Nome é obrigatório."), 400
        flash('Nome é obrigatório.', 'warning')
        return redirect(url_for('suppliers'))

    s.name  = name
    s.phone = phone or None
    s.email = email or None
    db.session.commit()
    if prefers_json:
        return jsonify(
            success=True,
            supplier={"id": s.id, "name": s.name, "phone": s.phone, "email": s.email},
        )
    flash('Fornecedor atualizado com sucesso!', 'success')
    return redirect(url_for('suppliers'))

@app.route('/suppliers/<int:supplier_id>/delete', methods=['POST'], endpoint='delete_supplier')
@login_required
def delete_supplier(supplier_id):
    u = current_user()
    s = Supplier.query.get_or_404(supplier_id)
    if getattr(s, 'user_id', None) and s.user_id != u.id:
        abort(403)

    prefers_json = (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.accept_mimetypes.best == "application/json"
    )
    db.session.delete(s)
    db.session.commit()
    if prefers_json:
        return jsonify(success=True)
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


def generate_lab_analysis_pdf_bytes(
    *,
    patient: Patient,
    context: dict[str, Any],
    doctor_display_name: str,
) -> bytes:
    """
    Gera o PDF do Ponza Lab (com prescrições e observações) e salva no banco.
    """
    from weasyprint import HTML
    u = current_user()

    patient_data = context.get("patient") or {}
    lines = []
    name = patient_data.get("nome") or patient.name
    if name:
        lines.append(f"Nome: {name}")
    birthdate = patient_data.get("data_nascimento") or (
        patient.birthdate.strftime("%d/%m/%Y") if patient.birthdate else None
    )
    if birthdate:
        lines.append(f"Data de nascimento: {birthdate}")
    cpf = patient_data.get("cpf") or (patient.cpf or "")
    if cpf:
        lines.append(f"CPF: {cpf}")
    lines.append(f"Médico responsável: {doctor_display_name}")
    patient_info = "\n".join(lines)

    exams = context.get("abnormal_exams") or context.get("exams") or []
    pdf_html = render_template(
        "lab_analysis_pdf.html",
        patient_info=patient_info,
        exams=exams,
        prescription=context.get("prescription") or [],
        orientations=context.get("orientations") or [],
        summary=context.get("summary") or "",
        generated_at=datetime.utcnow(),
        logo_url=_resolve_public_logo_url("ponzapdf.png"),
    )

    pdf_io = BytesIO()
    HTML(string=pdf_html, base_url=current_app.root_path).write_pdf(pdf_io)
    pdf_io.seek(0)

    try:
        pdf_bytes = pdf_io.getvalue()
        consult = Consult.query.filter_by(patient_id=patient.id).order_by(Consult.date.desc()).first()
        consult_id = consult.id if consult else None
        display_name = f"Analise_{(patient.name or 'Paciente').replace(' ', '_')}.pdf"
        _save_pdf_bytes_to_db(
            user_id=u.id,
            patient_id=patient.id,
            consult_id=consult_id,
            original_name=display_name,
            data=pdf_bytes,
            kind="lab_analysis_pdf",
        )
    except Exception as e:
        db.session.rollback()
        print("[PDF/gen] erro ao salvar PDF de analise no DB:", e)

    return pdf_io.getvalue()


# ------------------------------------------------------------------------------
# Finance / Cashbox API
# ------------------------------------------------------------------------------
@app.route('/finances', methods=['GET'], endpoint='finances')
@login_required
def finances_view():
    return serve_react_index()


@app.route('/api/finances/summary', methods=['GET'])
@login_required
def api_finances_summary():
    """Get financial summary with statistics."""
    user = g.user
    now = datetime.utcnow()
    
    # Timeframe filter
    timeframe = request.args.get('timeframe', '30d')
    days = {'7d': 7, '30d': 30, '90d': 90, '365d': 365}.get(timeframe, 30)
    start_date = now - timedelta(days=days)
    
    # Cashbox stats
    cashboxes = Cashbox.query.filter(Cashbox.user_id == user.id).all()
    open_cashboxes = [c for c in cashboxes if c.status == 'open']
    closed_cashboxes = [c for c in cashboxes if c.status == 'closed']
    total_balance = sum(c.current_balance for c in open_cashboxes)
    
    # Transaction stats for period
    transactions = CashboxTransaction.query.filter(
        CashboxTransaction.user_id == user.id,
        CashboxTransaction.created_at >= start_date
    ).all()
    
    total_income = sum(t.amount for t in transactions if t.type == 'income')
    total_expense = sum(abs(t.amount) for t in transactions if t.type == 'expense')
    net_result = total_income - total_expense
    
    # Payment stats
    payments = PatientPayment.query.filter(
        PatientPayment.user_id == user.id,
        PatientPayment.created_at >= start_date
    ).all()
    
    pending_payments = [p for p in payments if p.status == 'pending']
    paid_payments = [p for p in payments if p.status == 'paid']
    total_pending = sum(p.balance for p in pending_payments)
    total_received = sum(p.amount_paid for p in paid_payments)
    
    # Receivables by due date
    today = now.date()
    week_ahead = today + timedelta(days=7)
    receivables_today = sum(p.balance for p in pending_payments if p.due_date and p.due_date <= today)
    receivables_week = sum(p.balance for p in pending_payments if p.due_date and today < p.due_date <= week_ahead)
    receivables_later = sum(p.balance for p in pending_payments if p.due_date and p.due_date > week_ahead)
    
    # Monthly data for chart (last 6 months)
    monthly_data = []
    for i in range(5, -1, -1):
        month_start = (now - timedelta(days=30 * i)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if i > 0:
            month_end = (now - timedelta(days=30 * (i - 1))).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            month_end = now
        
        month_transactions = [t for t in transactions if month_start <= t.created_at < month_end]
        month_income = sum(t.amount for t in month_transactions if t.type == 'income')
        month_expense = sum(abs(t.amount) for t in month_transactions if t.type == 'expense')
        
        monthly_data.append({
            'month': month_start.strftime('%b'),
            'income': round(month_income, 2),
            'expense': round(month_expense, 2),
            'net': round(month_income - month_expense, 2)
        })
    
    # Payment method breakdown
    payment_methods = {}
    for t in transactions:
        if t.type == 'income' and t.payment_method:
            method = t.payment_method
            payment_methods[method] = payment_methods.get(method, 0) + t.amount
    
    # Average ticket
    paid_count = len(paid_payments)
    avg_ticket = total_received / paid_count if paid_count > 0 else 0
    
    return jsonify({
        'success': True,
        'summary': {
            'total_balance': round(total_balance, 2),
            'open_cashboxes': len(open_cashboxes),
            'closed_cashboxes': len(closed_cashboxes),
            'total_cashboxes': len(cashboxes),
            'total_income': round(total_income, 2),
            'total_expense': round(total_expense, 2),
            'net_result': round(net_result, 2),
            'margin_percent': round((net_result / total_income * 100) if total_income > 0 else 0, 1),
            'total_pending': round(total_pending, 2),
            'total_received': round(total_received, 2),
            'avg_ticket': round(avg_ticket, 2),
            'receivables': {
                'today': round(receivables_today, 2),
                'week': round(receivables_week, 2),
                'later': round(receivables_later, 2)
            }
        },
        'monthly_data': monthly_data,
        'payment_methods': {k: round(v, 2) for k, v in payment_methods.items()},
        'timeframe': timeframe
    })


@app.route('/api/cashboxes', methods=['GET', 'POST'])
@login_required
def api_cashboxes():
    """List or create cashboxes."""
    user = g.user
    
    if request.method == 'GET':
        status_filter = request.args.get('status', 'all')
        query = Cashbox.query.filter(Cashbox.user_id == user.id)
        
        if status_filter == 'open':
            query = query.filter(Cashbox.status == 'open')
        elif status_filter == 'closed':
            query = query.filter(Cashbox.status == 'closed')
        
        cashboxes = query.order_by(Cashbox.opened_at.desc()).all()
        
        result = []
        for cb in cashboxes:
            # Get today's transactions count
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            today_transactions = CashboxTransaction.query.filter(
                CashboxTransaction.cashbox_id == cb.id,
                CashboxTransaction.created_at >= today_start
            ).count()
            
            result.append({
                'id': cb.id,
                'name': cb.name,
                'description': cb.description,
                'type': cb.type,
                'status': cb.status,
                'initial_balance': cb.initial_balance,
                'current_balance': cb.current_balance,
                'responsible': cb.responsible,
                'opened_at': cb.opened_at.isoformat() if cb.opened_at else None,
                'closed_at': cb.closed_at.isoformat() if cb.closed_at else None,
                'today_transactions': today_transactions
            })
        
        return jsonify({'success': True, 'cashboxes': result})
    
    # POST - create new cashbox
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'error': 'Nome é obrigatório'}), 400
    
    cashbox = Cashbox(
        user_id=user.id,
        name=name,
        description=data.get('description', ''),
        type=data.get('type', 'manual'),
        initial_balance=float(data.get('initial_balance', 0)),
        current_balance=float(data.get('initial_balance', 0)),
        responsible=data.get('responsible', user.name or user.username),
        status='open'
    )
    db.session.add(cashbox)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'cashbox': {
            'id': cashbox.id,
            'name': cashbox.name,
            'status': cashbox.status,
            'current_balance': cashbox.current_balance
        }
    })


@app.route('/api/cashboxes/<int:cashbox_id>', methods=['GET', 'PUT', 'DELETE'])
@login_required
def api_cashbox_detail(cashbox_id):
    """Get, update, or delete a specific cashbox."""
    user = g.user
    cashbox = Cashbox.query.filter(
        Cashbox.id == cashbox_id,
        Cashbox.user_id == user.id
    ).first()
    
    if not cashbox:
        return jsonify({'success': False, 'error': 'Caixa não encontrado'}), 404
    
    if request.method == 'GET':
        # Get transactions for this cashbox
        transactions = CashboxTransaction.query.filter(
            CashboxTransaction.cashbox_id == cashbox_id
        ).order_by(CashboxTransaction.created_at.desc()).limit(100).all()
        
        return jsonify({
            'success': True,
            'cashbox': {
                'id': cashbox.id,
                'name': cashbox.name,
                'description': cashbox.description,
                'type': cashbox.type,
                'status': cashbox.status,
                'initial_balance': cashbox.initial_balance,
                'current_balance': cashbox.current_balance,
                'responsible': cashbox.responsible,
                'opened_at': cashbox.opened_at.isoformat() if cashbox.opened_at else None,
                'closed_at': cashbox.closed_at.isoformat() if cashbox.closed_at else None
            },
            'transactions': [{
                'id': t.id,
                'type': t.type,
                'category': t.category,
                'amount': t.amount,
                'description': t.description,
                'payment_method': t.payment_method,
                'created_at': t.created_at.isoformat()
            } for t in transactions]
        })
    
    if request.method == 'PUT':
        data = request.get_json() or {}
        
        # Handle closing the cashbox
        if data.get('action') == 'close':
            if cashbox.status == 'closed':
                return jsonify({'success': False, 'error': 'Caixa já está fechado'}), 400
            cashbox.status = 'closed'
            cashbox.closed_at = datetime.utcnow()
            db.session.commit()
            return jsonify({'success': True, 'message': 'Caixa fechado com sucesso'})
        
        # Handle reopening the cashbox
        if data.get('action') == 'reopen':
            if cashbox.status == 'open':
                return jsonify({'success': False, 'error': 'Caixa já está aberto'}), 400
            cashbox.status = 'open'
            cashbox.closed_at = None
            db.session.commit()
            return jsonify({'success': True, 'message': 'Caixa reaberto com sucesso'})
        
        # Regular update
        if 'name' in data:
            cashbox.name = data['name']
        if 'description' in data:
            cashbox.description = data['description']
        if 'responsible' in data:
            cashbox.responsible = data['responsible']
        
        db.session.commit()
        return jsonify({'success': True})
    
    if request.method == 'DELETE':
        db.session.delete(cashbox)
        db.session.commit()
        return jsonify({'success': True})


@app.route('/api/cashboxes/<int:cashbox_id>/transactions', methods=['POST'])
@login_required
def api_cashbox_add_transaction(cashbox_id):
    """Add a transaction to a cashbox."""
    user = g.user
    cashbox = Cashbox.query.filter(
        Cashbox.id == cashbox_id,
        Cashbox.user_id == user.id
    ).first()
    
    if not cashbox:
        return jsonify({'success': False, 'error': 'Caixa não encontrado'}), 404
    
    if cashbox.status == 'closed':
        return jsonify({'success': False, 'error': 'Não é possível adicionar transações a um caixa fechado'}), 400
    
    data = request.get_json() or {}
    trans_type = data.get('type', 'income')
    amount = float(data.get('amount', 0))
    
    if amount <= 0:
        return jsonify({'success': False, 'error': 'Valor deve ser maior que zero'}), 400
    
    # For expenses, store as negative
    if trans_type == 'expense':
        amount = -abs(amount)
    
    transaction = CashboxTransaction(
        cashbox_id=cashbox_id,
        user_id=user.id,
        type=trans_type,
        category=data.get('category'),
        amount=amount,
        description=data.get('description'),
        payment_method=data.get('payment_method'),
        reference=data.get('reference'),
        patient_payment_id=data.get('patient_payment_id')
    )
    
    # Update cashbox balance
    cashbox.current_balance += amount
    
    db.session.add(transaction)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'transaction': {
            'id': transaction.id,
            'amount': transaction.amount,
            'type': transaction.type
        },
        'new_balance': cashbox.current_balance
    })


@app.route('/api/patient_payments', methods=['GET', 'POST'])
@login_required
def api_patient_payments():
    """List or create patient payments."""
    user = g.user
    
    if request.method == 'GET':
        status_filter = request.args.get('status', 'all')
        patient_id = request.args.get('patient_id')
        
        query = PatientPayment.query.filter(PatientPayment.user_id == user.id)
        
        if status_filter == 'pending':
            query = query.filter(PatientPayment.status.in_(['pending', 'partial']))
        elif status_filter == 'paid':
            query = query.filter(PatientPayment.status == 'paid')
        
        if patient_id:
            query = query.filter(PatientPayment.patient_id == int(patient_id))
        
        payments = query.order_by(PatientPayment.created_at.desc()).limit(200).all()
        
        result = []
        for p in payments:
            patient = Patient.query.get(p.patient_id)
            result.append({
                'id': p.id,
                'patient_id': p.patient_id,
                'patient_name': patient.name if patient else 'Paciente removido',
                'amount': p.amount,
                'amount_paid': p.amount_paid,
                'balance': p.balance,
                'status': p.status,
                'payment_method': p.payment_method,
                'payment_type': p.payment_type,
                'description': p.description,
                'due_date': p.due_date.isoformat() if p.due_date else None,
                'paid_at': p.paid_at.isoformat() if p.paid_at else None,
                'insurance_name': p.insurance_name,
                'created_at': p.created_at.isoformat()
            })
        
        return jsonify({'success': True, 'payments': result})
    
    # POST - create new payment
    data = request.get_json() or {}
    patient_id = data.get('patient_id')
    amount = float(data.get('amount', 0))
    
    if not patient_id:
        return jsonify({'success': False, 'error': 'Paciente é obrigatório'}), 400
    if amount <= 0:
        return jsonify({'success': False, 'error': 'Valor deve ser maior que zero'}), 400
    
    # Verify patient exists and belongs to user
    patient = Patient.query.filter(
        Patient.id == patient_id,
        Patient.user_id == user.id
    ).first()
    
    if not patient:
        return jsonify({'success': False, 'error': 'Paciente não encontrado'}), 404
    
    due_date = None
    if data.get('due_date'):
        try:
            due_date = datetime.strptime(data['due_date'], '%Y-%m-%d').date()
        except ValueError:
            pass
    
    payment = PatientPayment(
        user_id=user.id,
        patient_id=patient_id,
        event_id=data.get('event_id'),
        amount=amount,
        amount_paid=0,
        payment_method=data.get('payment_method'),
        payment_type=data.get('payment_type', 'consultation'),
        status='pending',
        due_date=due_date,
        description=data.get('description'),
        notes=data.get('notes'),
        insurance_name=data.get('insurance_name'),
        insurance_authorization=data.get('insurance_authorization')
    )
    db.session.add(payment)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'payment': {
            'id': payment.id,
            'amount': payment.amount,
            'status': payment.status
        }
    })


@app.route('/api/patient_payments/<int:payment_id>', methods=['GET', 'PUT', 'DELETE'])
@login_required
def api_patient_payment_detail(payment_id):
    """Get, update, or delete a patient payment."""
    user = g.user
    payment = PatientPayment.query.filter(
        PatientPayment.id == payment_id,
        PatientPayment.user_id == user.id
    ).first()
    
    if not payment:
        return jsonify({'success': False, 'error': 'Pagamento não encontrado'}), 404
    
    if request.method == 'GET':
        patient = Patient.query.get(payment.patient_id)
        return jsonify({
            'success': True,
            'payment': {
                'id': payment.id,
                'patient_id': payment.patient_id,
                'patient_name': patient.name if patient else 'Paciente removido',
                'amount': payment.amount,
                'amount_paid': payment.amount_paid,
                'balance': payment.balance,
                'status': payment.status,
                'payment_method': payment.payment_method,
                'payment_type': payment.payment_type,
                'description': payment.description,
                'notes': payment.notes,
                'due_date': payment.due_date.isoformat() if payment.due_date else None,
                'paid_at': payment.paid_at.isoformat() if payment.paid_at else None,
                'insurance_name': payment.insurance_name,
                'insurance_authorization': payment.insurance_authorization,
                'created_at': payment.created_at.isoformat()
            }
        })
    
    if request.method == 'PUT':
        data = request.get_json() or {}
        
        # Handle payment receipt
        if data.get('action') == 'receive':
            amount_received = float(data.get('amount', 0))
            if amount_received <= 0:
                return jsonify({'success': False, 'error': 'Valor deve ser maior que zero'}), 400
            
            payment.amount_paid += amount_received
            payment.payment_method = data.get('payment_method') or payment.payment_method
            
            if payment.amount_paid >= payment.amount:
                payment.status = 'paid'
                payment.paid_at = datetime.utcnow()
            else:
                payment.status = 'partial'
            
            # Optionally add to cashbox
            cashbox_id = data.get('cashbox_id')
            if cashbox_id:
                cashbox = Cashbox.query.filter(
                    Cashbox.id == cashbox_id,
                    Cashbox.user_id == user.id,
                    Cashbox.status == 'open'
                ).first()
                
                if cashbox:
                    transaction = CashboxTransaction(
                        cashbox_id=cashbox_id,
                        user_id=user.id,
                        patient_payment_id=payment.id,
                        type='income',
                        category=payment.payment_type,
                        amount=amount_received,
                        description=f"Pagamento - {Patient.query.get(payment.patient_id).name if Patient.query.get(payment.patient_id) else 'Paciente'}",
                        payment_method=data.get('payment_method')
                    )
                    cashbox.current_balance += amount_received
                    db.session.add(transaction)
            
            db.session.commit()
            return jsonify({
                'success': True,
                'payment': {
                    'id': payment.id,
                    'amount_paid': payment.amount_paid,
                    'balance': payment.balance,
                    'status': payment.status
                }
            })
        
        # Regular update
        if 'description' in data:
            payment.description = data['description']
        if 'notes' in data:
            payment.notes = data['notes']
        if 'due_date' in data and data['due_date']:
            try:
                payment.due_date = datetime.strptime(data['due_date'], '%Y-%m-%d').date()
            except ValueError:
                pass
        if 'status' in data:
            payment.status = data['status']
        
        db.session.commit()
        return jsonify({'success': True})
    
    if request.method == 'DELETE':
        db.session.delete(payment)
        db.session.commit()
        return jsonify({'success': True})


@app.route('/api/patient/<int:patient_id>/payments', methods=['GET'])
@login_required
def api_patient_payments_list(patient_id):
    """Get all payments for a specific patient."""
    user = g.user
    
    patient = Patient.query.filter(
        Patient.id == patient_id,
        Patient.user_id == user.id
    ).first()
    
    if not patient:
        return jsonify({'success': False, 'error': 'Paciente não encontrado'}), 404
    
    payments = PatientPayment.query.filter(
        PatientPayment.patient_id == patient_id
    ).order_by(PatientPayment.created_at.desc()).all()
    
    total_charged = sum(p.amount for p in payments)
    total_paid = sum(p.amount_paid for p in payments)
    total_pending = sum(p.balance for p in payments if p.status in ['pending', 'partial'])
    
    return jsonify({
        'success': True,
        'patient': {
            'id': patient.id,
            'name': patient.name
        },
        'summary': {
            'total_charged': round(total_charged, 2),
            'total_paid': round(total_paid, 2),
            'total_pending': round(total_pending, 2)
        },
        'payments': [{
            'id': p.id,
            'amount': p.amount,
            'amount_paid': p.amount_paid,
            'balance': p.balance,
            'status': p.status,
            'payment_type': p.payment_type,
            'payment_method': p.payment_method,
            'description': p.description,
            'due_date': p.due_date.isoformat() if p.due_date else None,
            'paid_at': p.paid_at.isoformat() if p.paid_at else None,
            'created_at': p.created_at.isoformat()
        } for p in payments]
    })


# ------------------------------------------------------------------------------
# Erros / Contexto
# ------------------------------------------------------------------------------
@app.context_processor
def inject_globals():
    return {"now": datetime.utcnow()}

@app.errorhandler(403)
def forbidden(e):
    if _request_wants_json():
        return jsonify({"error": "forbidden"}), 403
    return "403 - Proibido", 403

@app.errorhandler(404)
def not_found(e):
    if _request_wants_json():
        return jsonify({"error": "not_found"}), 404
    return "404 - Não encontrado", 404

@app.errorhandler(500)
def server_error(e):
    if _request_wants_json():
        return jsonify({"error": "server_error"}), 500
    return "500 - Erro interno", 500

# ------------------------------------------------------------------------------
# Entrypoint
# ------------------------------------------------------------------------------
if __name__ == '__main__':
    debug_enabled = os.getenv("FLASK_DEBUG", "0").strip() == "1"
    app.run(host='0.0.0.0', port=int(os.getenv("PORT", "5000")), debug=debug_enabled)

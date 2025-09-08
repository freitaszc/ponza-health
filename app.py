import os
import re
import secrets
from io import BytesIO
from weasyprint import HTML
from functools import wraps
from datetime import datetime, timedelta
from typing import Any, Optional, Callable, cast

from dotenv import load_dotenv
from flask import (
    Flask, render_template, render_template_string, request, redirect, url_for,
    session, flash, jsonify, abort, send_file, g
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import select, text, func
from werkzeug.middleware.proxy_fix import ProxyFix
from jinja2 import TemplateNotFound

from models import (
    db, User, Patient, Doctor, Consult, PackageUsage,
    Supplier, Product, AgendaEvent, Quote, Reference, Video
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
DEFAULT_PATIENT_IMAGE = "images/patient-icon.png"

def allowed_file(filename: str) -> bool:
    return bool(filename) and '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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

db.init_app(app)
with app.app_context():
    try:
        db.create_all()
    except Exception as e:
        print("[DB] create_all error:", e)
        try:
            with db.engine.connect() as conn:
                conn.execute(text("PRAGMA journal_mode=WAL"))
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

        # PATIENTS (novas/garantias)
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
        add_column_if_missing("patients", "profile_image VARCHAR(200)", "profile_image")  # NOVO

        # AGENDA_EVENTS
        add_column_if_missing("agenda_events", "notes TEXT", "notes")
        add_column_if_missing("agenda_events", "type VARCHAR(20)", "type")
        add_column_if_missing("agenda_events", "billing VARCHAR(20)", "billing")
        add_column_if_missing("agenda_events", "insurer VARCHAR(120)", "insurer")

        # PRODUCTS (novas colunas opcionais usadas no modelo)
        add_column_if_missing("products", "code VARCHAR(64)", "code")
        add_column_if_missing("products", "category VARCHAR(80)", "category")
        add_column_if_missing("products", "application_route VARCHAR(80)", "application_route")
        add_column_if_missing("products", "min_stock INTEGER DEFAULT 0", "min_stock")

        # DOCTORS
        add_column_if_missing("doctors", "crm VARCHAR(50)", "crm")
        add_column_if_missing("doctors", "email VARCHAR(120)", "email")
        add_column_if_missing("doctors", "phone VARCHAR(50)", "phone")
        add_column_if_missing("doctors", "specialty VARCHAR(120)", "specialty")

with app.app_context():
    try:
        apply_minimal_migrations()
    except Exception as e:
        print("[MIGRATION] erro geral:", e)

# ------------------------------------------------------------------------------
# Helpers / Auth
# ------------------------------------------------------------------------------
def get_logged_user() -> Optional[User]:
    uid = session.get('user_id')
    return User.query.get(uid) if uid else None

def login_required(f: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(f)
    def wrapper(*args, **kwargs):
        u = get_logged_user()
        if not u:
            return redirect(url_for('login'))
        g.user = u
        return f(*args, **kwargs)
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
# Páginas Públicas / Auth
# ------------------------------------------------------------------------------
@app.route('/')
def hero():
    return render_template("hero.html")

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm', '')

        if not username or not email or not password:
            flash('Preencha todos os campos.', 'warning')
            return redirect(url_for('register'))
        if not basic_email(email):
            flash('E-mail inválido.', 'warning')
            return redirect(url_for('register'))
        if password != confirm:
            flash('As senhas não coincidem.', 'warning')
            return redirect(url_for('register'))

        if User.query.filter_by(username=username).first() or User.query.filter_by(email=email).first():
            flash('Já existe um usuário com esse username ou e-mail.', 'warning')
            return redirect(url_for('register'))

        user = User(username=username, email=email, password_hash=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()
        flash('Cadastro realizado! Faça login para continuar.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        login_input = request.form.get('login', '').strip()
        pwd         = request.form.get('password', '')

        if '@' in login_input:
            user = User.query.filter(User.email == login_input.lower()).first()
        else:
            user = User.query.filter(User.username == login_input).first()
            if not user and login_input.lower() == 'admin':
                user = User.query.filter(User.username == 'admin').first()

        stored_hash = getattr(user, 'password_hash', None) if user else None

        if not user or not stored_hash or not check_password_hash(stored_hash, pwd):
            error = 'Usuário ou senha inválidos.'
        else:
            session['user_id']  = user.id
            session['username'] = user.username
            flash('Login realizado com sucesso!', 'success')
            return redirect(url_for('index'))

    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/privacy_policy')
def privacy_policy():
    return render_template("privacy_policy.html")

@app.route('/about')
def about():
    return render_template("about.html")

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
    # Gráfico grande (Consultas/dia nos últimos 7 dias)
    #  - count = número de Consult por dia
    #  - media = média progressiva até o dia
    # ---------------------------------------
    rows_agg = (
        db.session.query(Consult.date, func.count(Consult.id))
        .join(Patient, Patient.id == Consult.patient_id)
        .filter(
            Patient.owner_user_id == u.id,
            Consult.date >= start_7,
            Consult.date <= today
        )
        .group_by(Consult.date)
        .all()
    )
    counts_by_day = {d: int(c) for d, c in rows_agg}

    series = []
    running_sum = 0
    for i in range(7):
        d = start_7 + timedelta(days=i)
        c = counts_by_day.get(d, 0)
        running_sum += c
        avg = round(running_sum / (i + 1), 2)
        series.append({
            "date": d.strftime("%d/%m"),
            "count": c,
            "media": avg
        })
    quiz_chart_data = series

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

    # Sexo (contagem simples — ajusta se quiser por janela)
    male_aliases = {"m", "masculino", "homem", "male"}
    female_aliases = {"f", "feminino", "mulher", "female"}

    patients_30_objs = (
        Patient.query
        .filter(Patient.owner_user_id == u.id)
        .all()
    )
    male_count = sum(1 for p in patients_30_objs if (p.sex or "").strip().lower() in male_aliases)
    female_count = sum(1 for p in patients_30_objs if (p.sex or "").strip().lower() in female_aliases)

    # ---------------------------------------
    # Donut "Procedimentos realizados" (últimos 30 dias)
    # ---------------------------------------
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

    # ---------------------------------------
    # Donut "Pacientes x Convênio" (últimos 30 dias)
    # ---------------------------------------
    insurance_particular_30 = sum(1 for e in events_30 if (e.billing or "").lower() == "particular")
    insurance_convenio_30   = sum(1 for e in events_30 if (e.billing or "").lower() == "convenio")

    # ---------------------------------------
    # NOVO: Estoque baixo (qtd < 5)
    # ---------------------------------------
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

    # ---------------------------------------
    # NOVO: Cotações respondidas + tabela (robusto a diferentes esquemas)
    #  - quotes_items: lista para a tabela (name/subject, responses)
    #  - quotes_total / quotes_responded / quotes_pending consistentes
    # ---------------------------------------
    quotes_items = []
    quotes_total = 0
    quotes_responded = 0
    quotes_pending = 0

    try:
        base = Quote.query
        col_user_id = getattr(Quote, "user_id", None)

        if col_user_id is not None:
            base = base.filter(col_user_id == u.id)

        # ordena por created_at se existir
        try:
            quotes_list = base.order_by(Quote.created_at.desc()).all()
        except Exception:
            quotes_list = base.all()

        quotes_total = len(quotes_list)

        # 2) Estratégias para contar respostas
        responses_by_quote_id = {}
        used_strategy = None

        # 2.1) Modelo QuoteResponse?
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

        # 2.2) Status na própria Quote?
        if used_strategy is None:
            try:
                responded_status = {"respondida", "respondido", "finalizada", "fechada", "responded"}
                for q in quotes_list:
                    status_val = (getattr(q, "status", "") or "").strip().lower()
                    responses_by_quote_id[getattr(q, "id", None)] = 1 if status_val in responded_status else 0
                used_strategy = "status"
            except Exception:
                pass

        # 2.3) Campo genérico "responses" na Quote?
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
            used_strategy = "inline_responses"

        # 3) Monta itens e estatísticas
        for q in quotes_list:
            qid = getattr(q, "id", None)
            title = getattr(q, "title", None) or getattr(q, "name", None) or f"Cotação #{qid or ''}"
            resp_count = int(responses_by_quote_id.get(qid, 0))
            quotes_items.append({"name": title, "responses": resp_count})

        quotes_responded = sum(1 for it in quotes_items if it["responses"] > 0)
        quotes_pending = max(quotes_total - quotes_responded, 0)

    except Exception as e:
        print("[INDEX] quotes stats/table error:", e)
        # mantém 0/[] em falha

    # ---------------------------------------
    # Render
    # ---------------------------------------
    return render_template(
        'index.html',
        # métricas gerais
        total_patients=total_patients,
        total_consults=total_consults,
        used=used,
        remaining=remaining,
        package_used=used,
        package_limit=total,
        package_total=total,
        # gráfico (7 dias)
        quiz_chart_data=quiz_chart_data,
        # donuts (30 dias)
        patients_new_30=patients_new_30,
        patients_return_30=patients_return_30,
        male_count=male_count,
        female_count=female_count,
        procedures_return_30=procedures_return_30,
        procedures_first_30=procedures_first_30,
        insurance_particular_30=insurance_particular_30,
        insurance_convenio_30=insurance_convenio_30,
        # widgets novos
        low_stock=low_stock,
        quotes_total=quotes_total,
        quotes_responded=quotes_responded,
        quotes_pending=quotes_pending,
        quotes_items=quotes_items,   # <<--- adicionado
        # opcional para badge no sino
        notifications_unread=0
    )

# ------------------------------------------------------------------------------
# Compra de Pacotes
# ------------------------------------------------------------------------------
@app.route('/purchase', methods=['GET', 'POST'])
@login_required
def purchase():
    if request.method == 'POST':
        pacote = request.form.get('package', '')
        valor  = {'50': 120, '150': 300, '500': 950}.get(pacote)
        if not valor:
            flash('Selecione um pacote válido.', 'warning')
            return redirect(url_for('purchase'))
        try:
            from mercado_pago import generate_payment_link
            link = generate_payment_link(pacote, valor)
        except Exception:
            link = None
        return redirect(link or url_for('purchase'))
    try:
        return render_template('purchase.html')
    except TemplateNotFound:
        return render_template_string("""
        <h1>Comprar créditos</h1>
        <form method="post">
            <select name="package">
                <option value="50">50</option>
                <option value="150">150</option>
                <option value="500">500</option>
            </select>
            <button type="submit">Comprar</button>
        </form>
        <p><a href="{{ url_for('index') }}">Voltar</a></p>
        """)

# ------------------------------------------------------------------------------
# Conta
# ------------------------------------------------------------------------------
@app.route('/account')
@login_required
def account():
    return render_template('account.html')

@app.route('/remove_profile_image', methods=['POST'], endpoint='remove_profile_image')
@login_required
def remove_profile_image():
    u = current_user()
    default_rel = DEFAULT_USER_IMAGE

    rel = (u.profile_image or "").replace("\\", "/")

    if rel and rel != default_rel:
        abs_path = os.path.join(STATIC_DIR, rel)
        try:
            allowed_root = os.path.realpath(os.path.join(STATIC_DIR, "uploads", "profiles"))
            abs_norm = os.path.realpath(abs_path)
            if abs_norm.startswith(allowed_root) and os.path.exists(abs_norm):
                os.remove(abs_norm)
        except Exception as e:
            print("[profile_image] remove error:", e)

    u.profile_image = default_rel
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

        dest_dir = os.path.join(STATIC_DIR, "uploads", "profiles")
        os.makedirs(dest_dir, exist_ok=True)

        new_name = f"user_{u.id}_{int(_time.time())}.{ext}"
        dest_path = os.path.join(dest_dir, new_name)
        file.save(dest_path)

        rel_path = os.path.relpath(dest_path, STATIC_DIR).replace("\\", "/")
        u.profile_image = rel_path

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

    references_path = os.path.join(app.root_path, "json", "references.json")

    # ==========================
    # 1) INSERÇÃO MANUAL
    # ==========================
    if request.form.get('manual_entry') == '1':
        name_form    = (request.form.get('name') or '').strip()
        age_s        = (request.form.get('age') or '').strip()
        cpf_form     = (request.form.get('cpf') or '').strip()
        gender_form  = (request.form.get('gender') or '').strip()
        phone_form   = (request.form.get('phone') or '').strip()
        doctor_form  = (request.form.get('doctor') or '').strip()
        lab_results  = (request.form.get('lab_results') or '').strip()

        if not lab_results:
            return redirect(url_for('upload', error="Digite os resultados no campo de texto."))

        try:
            dgn, rx, name_ai, gender_ai, age_ai, cpf_ai, phone_ai, doctor_ai = analyze_pdf(
                lab_results, references_path=references_path, manual=True
            )
        except Exception as e:
            print("[PDF] manual analyze error:", e)
            return redirect(url_for('upload', error="Falha ao analisar o texto manual."))

        name   = name_form or name_ai or 'Paciente (manual)'
        gender = gender_form or gender_ai or None
        cpf    = cpf_form or cpf_ai or ''
        phone  = phone_form or phone_ai or ''
        doctor_name = doctor_form or doctor_ai or ''

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

        # Resolve doctor_id (NUNCA deixar None)
        doctor_id = None
        if doctor_name:
            doc = Doctor.query.filter(Doctor.name.ilike(doctor_name)).first()
            if doc:
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
        # como a coluna é NOT NULL, setamos explicitamente:
        if hasattr(c, "doctor_id"):
            c.doctor_id = doctor_id

        db.session.add(c)
        db.session.commit()

        return redirect(url_for('upload', success=1, success_id=p.id))

    # ==========================
    # 2) UPLOAD DE PDF
    # ==========================
    file = request.files.get('pdf_file') or request.files.get('file') or request.files.get('pdf')
    if not file or not (file.filename and file.filename.strip()):
        return redirect(url_for('upload', error="Nenhum arquivo selecionado."))

    raw_name = file.filename
    if not allowed_file(raw_name) or not raw_name.lower().endswith('.pdf'):
        return redirect(url_for('upload', error="Tipo de arquivo não permitido. Envie um PDF."))

    try:
        filename = secure_filename(raw_name)
        base, ext = os.path.splitext(filename)
        unique_name = f"{base}_{int(datetime.utcnow().timestamp())}{ext or '.pdf'}"
        dest_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
        file.save(dest_path)
    except Exception as e:
        print("[UPLOAD] erro ao salvar:", e)
        return redirect(url_for('upload', error="Falha ao salvar o arquivo."))

    try:
        dgn, rx, name_ai, gender_ai, age_ai, cpf_ai, phone_ai, doctor_ai = analyze_pdf(
            dest_path, references_path=references_path, manual=False
        )
    except Exception as e:
        print("[PDF] analyze error:", e)
        # Mesmo com erro, vamos criar consulta com médico padrão para não quebrar
        dgn, rx, name_ai, gender_ai, age_ai, cpf_ai, phone_ai, doctor_ai = (
            "Error reading PDF or references.", "", "", "", 0, "", "", ""
        )

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

    return redirect(url_for('upload', success=1, success_id=p.id))

@app.route('/download_pdf/<int:patient_id>')
@login_required
def download_pdf(patient_id):
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

    # HTML do PDF (logo via url_for no template)
    html_str = render_template(
        "result_pdf.html",
        patient_info=patient_info,
        diagnostic_text=diagnostic_text,
        prescription_text=prescription_text,
        doctor_name=(getattr(u, "name", None) or u.username),
    )

    from io import BytesIO
    pdf_io = BytesIO()

    # Tenta com WeasyPrint (renderiza o HTML completo com a logo SVG)
    try:
        from weasyprint import HTML
        HTML(string=html_str, base_url=request.host_url).write_pdf(pdf_io)
        pdf_io.seek(0)
    except Exception:
        # Fallback: ReportLab com logo PNG
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas
            from reportlab.lib.units import mm
            from reportlab.lib.utils import ImageReader
            import os

            c = canvas.Canvas(pdf_io, pagesize=A4)
            width, height = A4

            # Desenha a logo PNG no topo direito, se existir
            png_path = os.path.join(STATIC_DIR, "images", "logo.png")
            if os.path.exists(png_path):
                try:
                    img = ImageReader(png_path)
                    # ~40mm de largura mantendo proporção
                    target_w = 40 * mm
                    iw, ih = img.getSize()
                    ratio = target_w / iw
                    target_h = ih * ratio
                    c.drawImage(img, width - target_w - 15*mm, height - target_h - 15*mm,
                                width=target_w, height=target_h, preserveAspectRatio=True, mask='auto')
                except Exception:
                    pass  # se der algum erro, ignora a logo no fallback

            # Título
            c.setFont("Times-Bold", 16)
            c.drawCentredString(width / 2, height - 20 * mm, "Resultado da Análise - Ponza Health")

            # Bloco do paciente
            c.setFont("Times-Roman", 11)
            y = height - 35 * mm
            for ln in patient_info.splitlines():
                c.drawString(20 * mm, y, ln)
                y -= 6 * mm

            # Diagnóstico
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

            # Prescrição
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

            # Assinatura
            c.setFont("Times-Roman", 11)
            c.line(60 * mm, 25 * mm, 150 * mm, 25 * mm)
            c.drawCentredString(105 * mm, 20 * mm, getattr(u, "name", None) or u.username)

            c.showPage()
            c.save()
            pdf_io.seek(0)
        except Exception as e2:
            return jsonify(success=False, error=f"Falha ao gerar PDF: {e2}"), 500

    filename = f"Resultado_{(patient.name or 'Paciente').replace(' ', '_')}.pdf"
    return send_file(pdf_io, as_attachment=True, download_name=filename, mimetype="application/pdf")

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
# Agenda (API)
# ------------------------------------------------------------------------------
@app.route('/api/add_event', methods=['POST'])
@login_required
def api_add_event():
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

    try:
        start_dt = datetime.fromisoformat(start_s)
    except Exception:
        return jsonify(success=False, error="Formato de data/hora inválido."), 400

    if end_s:
        try:
            end_dt = datetime.fromisoformat(end_s)
        except Exception:
            return jsonify(success=False, error="Formato de término inválido."), 400
    else:
        end_dt = start_dt + timedelta(hours=1)

    ev = AgendaEvent(
        user_id=u.id, title=title, start=start_dt, end=end_dt,
        notes=notes or None, type=type_ or None, billing=billing or None, insurer=insurer or None
    )
    db.session.add(ev)
    db.session.commit()

    return jsonify(success=True, event_id=ev.id), 201

@app.route('/api/events/<int:event_id>', methods=['PUT'])
@login_required
def api_update_event(event_id):
    u = current_user()
    ev = AgendaEvent.query.get_or_404(event_id)
    if getattr(ev, 'user_id', None) != u.id:
        abort(403)

    data = request.get_json(silent=True) or {}

    start_s = (data.get('start') or '').strip()
    end_s   = (data.get('end') or '').strip()

    if start_s:
        try:
            ev.start = datetime.fromisoformat(start_s)
        except Exception:
            return jsonify(success=False, error="Formato de data/hora inválido para 'start'."), 400

    if end_s:
        try:
            ev.end = datetime.fromisoformat(end_s)
        except Exception:
            return jsonify(success=False, error="Formato de data/hora inválido para 'end'."), 400

    for key in ('title', 'notes', 'type', 'billing', 'insurer'):
        if key in data:
            try:
                setattr(ev, key, (data.get(key) or '').strip() or None)
            except Exception:
                pass

    db.session.commit()
    return jsonify(success=True)

@app.route('/api/events')
@login_required
def api_events():
    u = current_user()
    doctor_id = request.args.get('doctor_id', type=int)

    events = []

    ag = AgendaEvent.query.filter_by(user_id=u.id).all()
    for e in ag:
        events.append({
            "id": getattr(e, "id", None),
            "title": e.title or "Evento",
            "start": e.start.isoformat() if e.start else None,
            "end":   e.end.isoformat()   if e.end   else None,
            "allDay": False,
            "extendedProps": {
                "notes": getattr(e, "notes", None),
                "type": getattr(e, "type", None),
                "billing": getattr(e, "billing", None),
                "insurer": getattr(e, "insurer", None),
            },
            "className": "holiday-event" if (getattr(e, "type", "") == "bloqueio") else "patient-event"
        })

    q = Consult.query
    if doctor_id:
        q = q.filter_by(doctor_id=doctor_id)
    consults = q.all()
    for c in consults:
        if c.time:
            start = datetime.combine(c.date, c.time).isoformat()
            events.append({
                "title": c.notes or "Consulta",
                "start": start,
                "allDay": False,
                "className": "patient-event",
                "extendedProps": {"type": "consulta"}
            })
        else:
            events.append({
                "title": c.notes or "Consulta",
                "start": c.date.isoformat(),
                "allDay": True,
                "className": "patient-event",
                "extendedProps": {"type": "consulta"}
            })

    return jsonify(events)

# ------------------------------------------------------------------------------
# Catálogo / Pacientes
# ------------------------------------------------------------------------------
@app.route('/catalog/register', methods=['GET', 'POST'])
@login_required
def register_patient():
    import time as _time

    u = current_user()
    if request.method == 'POST':
        name        = (request.form.get('name') or '').strip()
        birthdate_s = (request.form.get('birthdate') or '').strip()
        sex         = (request.form.get('sex') or '').strip()

        email       = (request.form.get('email') or '').strip().lower()
        cpf         = (request.form.get('cpf') or '').strip().replace('.', '').replace('-', '')
        notes       = (request.form.get('notes') or '').strip()

        phone_pri   = (request.form.get('phone_primary') or '').strip()
        phone_sec   = (request.form.get('phone_secondary') or '').strip()

        cep         = (request.form.get('cep') or '').strip()
        street      = (request.form.get('street') or '').strip()
        number      = (request.form.get('number') or '').strip()
        complement  = (request.form.get('complement') or '').strip()
        district    = (request.form.get('district') or '').strip()
        city        = (request.form.get('city') or '').strip()
        state       = (request.form.get('state') or '').strip().upper()

        errs = []
        if not name: errs.append("Nome é obrigatório.")
        if not birthdate_s: errs.append("Data de nascimento é obrigatória.")
        if not sex: errs.append("Sexo é obrigatório.")
        if not phone_pri: errs.append("Celular é obrigatório.")
        try:
            birthdate = datetime.fromisoformat(birthdate_s).date()
        except Exception:
            errs.append("Data de nascimento inválida.")
            birthdate = None

        if email and not basic_email(email):
            errs.append("E-mail inválido.")
        if state and len(state) not in (0, 2):
            errs.append("Estado deve ser a sigla (UF).")

        # Processa imagem (opcional)
        profile_rel = DEFAULT_PATIENT_IMAGE
        file = request.files.get('profile_image')
        if file and file.filename:
            if not allowed_file(file.filename):
                errs.append("Foto do paciente: use PNG, JPG ou JPEG.")
            else:
                filename = secure_filename(file.filename)
                ext = filename.rsplit('.', 1)[1].lower()
                dest_dir = os.path.join(STATIC_DIR, "uploads", "patients")
                os.makedirs(dest_dir, exist_ok=True)
                new_name = f"patient_{u.id}_{int(_time.time())}.{ext}"
                dest_path = os.path.join(dest_dir, new_name)
                file.save(dest_path)
                profile_rel = os.path.relpath(dest_path, STATIC_DIR).replace("\\", "/")

        if errs:
            for e in errs: flash(e, "warning")
            return redirect(url_for('register_patient'))

        p = Patient(
            owner_user_id=u.id,
            name=name,
            birthdate=birthdate,
            sex=sex,
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

    doctors_list = Doctor.query.order_by(Doctor.name).all()
    return render_template('catalog.html', patients=patients, doctors=doctors_list)

@app.route('/edit_patient/<int:patient_id>', methods=['GET', 'POST'])
@login_required
def edit_patient(patient_id):
    import time as _time

    u = current_user()
    patient = Patient.query.get_or_404(patient_id)
    if patient.owner_user_id != u.id:
        abort(403)

    if request.method == 'POST':
        name        = (request.form.get('name') or '').strip()
        birthdate_s = (request.form.get('birthdate') or '').strip()
        sex         = (request.form.get('sex') or '').strip()

        email       = (request.form.get('email') or '').strip().lower()
        cpf         = (request.form.get('cpf') or '').strip().replace('.', '').replace('-', '')
        notes       = (request.form.get('notes') or '').strip()

        phone_pri   = (request.form.get('phone_primary') or '').strip()
        phone_sec   = (request.form.get('phone_secondary') or '').strip()

        cep         = (request.form.get('cep') or '').strip()
        street      = (request.form.get('street') or '').strip()
        number      = (request.form.get('number') or '').strip()
        complement  = (request.form.get('complement') or '').strip()
        district    = (request.form.get('district') or '').strip()
        city        = (request.form.get('city') or '').strip()
        state       = (request.form.get('state') or '').strip().upper()

        errs = []
        if not name: errs.append("Nome é obrigatório.")
        if not birthdate_s: errs.append("Data de nascimento é obrigatória.")
        if not sex: errs.append("Sexo é obrigatório.")
        if not phone_pri: errs.append("Celular é obrigatório.")
        try:
            birthdate = datetime.fromisoformat(birthdate_s).date()
        except Exception:
            errs.append("Data de nascimento inválida.")
            birthdate = None

        if email and not basic_email(email):
            errs.append("E-mail inválida.")
        if state and len(state) not in (0, 2):
            errs.append("Estado deve ser a sigla (UF).")

        # foto nova (opcional)
        file = request.files.get('profile_image')
        if file and file.filename:
            if not allowed_file(file.filename):
                errs.append("Foto do paciente: use PNG, JPG ou JPEG.")
            else:
                filename = secure_filename(file.filename)
                ext = filename.rsplit('.', 1)[1].lower()
                dest_dir = os.path.join(STATIC_DIR, "uploads", "patients")
                os.makedirs(dest_dir, exist_ok=True)
                new_name = f"patient_{u.id}_{int(_time.time())}.{ext}"
                dest_path = os.path.join(dest_dir, new_name)
                file.save(dest_path)
                rel_path = os.path.relpath(dest_path, STATIC_DIR).replace("\\", "/")
                patient.profile_image = rel_path

        if errs:
            for e in errs: flash(e, "warning")
            return redirect(url_for('edit_patient', patient_id=patient.id))

        patient.name            = name
        patient.birthdate       = birthdate
        patient.sex             = sex
        patient.email           = email or None
        patient.cpf             = cpf or None
        patient.notes           = notes or None
        patient.phone_primary   = phone_pri
        patient.phone_secondary = phone_sec or None
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

@app.route('/patient_info/<int:patient_id>')
@login_required
def patient_info(patient_id):
    u = current_user()
    patient = Patient.query.get_or_404(patient_id)
    if patient.owner_user_id != u.id:
        abort(403)
    return render_template('patient_info.html', patient=patient)

# API JSON (compat)
@app.route('/api/add_patient', methods=['POST'])
@login_required
def api_add_patient():
    u = current_user()
    data = request.get_json() or {}

    name        = (data.get("name") or "").strip()
    birthdate_s = (data.get("birthdate") or "").strip()
    sex         = (data.get("sex") or data.get("gender") or "").strip()
    email       = (data.get("email") or "").strip().lower()
    cpf         = (data.get("cpf") or "").strip()
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

    if not (name and birthdate_s and sex and phone_pri):
        return jsonify(success=False, error='Campos obrigatórios: nome, data de nascimento, sexo, celular.'), 400

    try:
        birthdate = datetime.fromisoformat(birthdate_s).date()
    except Exception:
        return jsonify(success=False, error='Data de nascimento inválida'), 400

    if email and not basic_email(email):
        return jsonify(success=False, error='E-mail inválido'), 400

    p = Patient(
        owner_user_id=u.id,
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
def get_or_create_default_doctor() -> int:
    name = "(Sem médico)"
    try:
        doc = Doctor.query.filter(Doctor.name == name).first()
    except Exception:
        # Se falhar por coluna faltando, tenta migrar e refaz
        try:
            apply_minimal_migrations()
        except Exception:
            pass
        doc = Doctor.query.filter(Doctor.name == name).first()

    if not doc:
        doc = Doctor(name=name)  # crm pode ficar nulo
        db.session.add(doc)
        db.session.commit()
    return doc.id

@app.route('/doctors')
@login_required
def doctors():
    q = (request.args.get('q') or '').strip().lower()
    specialty_f = (request.args.get('specialty') or '').strip()

    base = Doctor.query

    if q:
        like = f"%{q}%"
        base = base.filter(
            db.or_(
                Doctor.name.ilike(like),
                Doctor.crm.ilike(like),
                Doctor.specialty.ilike(like),
                Doctor.email.ilike(like)
            )
        )

    if specialty_f:
        base = base.filter(Doctor.specialty == specialty_f)

    items = base.order_by(Doctor.id.desc()).all()

    # lista de especialidades (distintas) para o select
    specs = [r[0] for r in db.session.query(Doctor.specialty)
             .filter(Doctor.specialty.isnot(None))
             .filter(Doctor.specialty != '')
             .distinct()
             .order_by(Doctor.specialty.asc())
             .all()]

    return render_template('doctors.html', doctors=items, specialties=specs, notifications_unread=0)


@app.route('/api_doctors')
def api_doctors():
    docs = Doctor.query.order_by(Doctor.name).all()
    return jsonify([{"id": d.id, "name": d.name} for d in docs])

@app.route('/doctors/add', methods=['POST'], endpoint='add_doctor_route')
@login_required
def add_doctor_route():
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

    d = Doctor(
        name=name or None,
        crm=crm or None,
        email=email or None,
        phone=phone or None,
        specialty=specialty or None
    )

    db.session.add(d)
    db.session.commit()
    flash('Profissional cadastrado com sucesso!', 'success')
    return redirect(url_for('doctors'))

# ------------------------------------------------------------------------------
# Cotações / Fornecedores / Produtos
# ------------------------------------------------------------------------------
@app.route('/quotes', methods=['GET'], endpoint='quote_index')
@login_required
def quotes_index():
    quotes = Quote.query.order_by(Quote.created_at.desc()).all()
    try:
        return render_template('quote_index.html', quotes=quotes)
    except TemplateNotFound:
        items = "".join(
            f"<li><strong>{q.title}</strong> — {q.created_at.strftime('%d/%m/%Y %H:%M')}</li>"
            for q in quotes
        )
        return f"""
            <!doctype html><meta charset="utf-8">
            <h1>Cotações</h1>
            <ul>{items or "<li>(vazio)</li>"}</ul>
            <p><a href="{url_for('index')}">Voltar</a></p>
        """

@app.route('/create_quote', methods=['GET', 'POST'])
@login_required
def create_quote():
    from json import loads, dumps
    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        items_raw = (request.form.get('items') or '').strip()
        supplier_ids = request.form.getlist('supplier_ids')

        if not title or not items_raw or not supplier_ids:
            flash('Preencha título, itens e fornecedores.', 'warning')
            return redirect(url_for('create_quote'))

        try:
            parsed = loads(items_raw)
            if isinstance(parsed, list):
                items_norm = [str(x).strip() for x in parsed if str(x).strip()]
            elif isinstance(parsed, dict):
                items_norm = parsed
            else:
                items_norm = [str(parsed).strip()]
        except Exception:
            items_norm = [ln.strip() for ln in items_raw.splitlines() if ln.strip()]

        suppliers_norm = []
        for sid in supplier_ids:
            sid = sid.strip()
            if sid:
                suppliers_norm.append(int(sid) if sid.isdigit() else sid)

        q = Quote(
            title=title,
            items=dumps(items_norm, ensure_ascii=False),
            suppliers=dumps(suppliers_norm, ensure_ascii=False),
        )
        db.session.add(q)
        db.session.commit()
        flash('Cotação criada.', 'success')
        return redirect(url_for('quote_index'))

    suppliers = Supplier.query.order_by(Supplier.name.asc()).all()
    try:
        return render_template('quote_new.html', suppliers=suppliers)
    except TemplateNotFound:
        return render_template('create_quote.html')

@app.route('/quotes/<int:quote_id>', methods=['GET'], endpoint='quote_view')
@login_required
def quotes_view(quote_id):
    q = Quote.query.get_or_404(quote_id)
    try:
        return render_template('quote_view.html', quote=q)
    except TemplateNotFound:
        return render_template_string("""
        <h1>Visualizar Cotação</h1>
        <p><strong>Título:</strong> {{ q.title }}</p>
        <p><strong>Itens:</strong><br><pre>{{ q.items }}</pre></p>
        <p><strong>Fornecedores:</strong><br><pre>{{ q.suppliers }}</pre></p>
        <p><a href="{{ url_for('quote_index') }}">Voltar</a></p>
        """, q=q)

app.add_url_rule('/quotes/<int:quote_id>/show', endpoint='quote_show', view_func=quotes_view, methods=['GET'])

@app.route('/quotes/<int:quote_id>/delete', methods=['POST'], endpoint='quote_delete')
@login_required
def quotes_delete(quote_id):
    q = Quote.query.get_or_404(quote_id)
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

@app.route('/products')
@login_required
def products():
    u = current_user()
    prods = Product.query.filter_by(user_id=u.id).order_by(Product.created_at.desc()).all()
    try:
        return render_template('products.html', products=prods)
    except TemplateNotFound:
        lis = "".join(f"<li>{p.name} — R$ {p.sale_price:.2f} (qtde: {p.quantity})</li>" for p in prods)
        return f"<h1>Produtos</h1><ul>{lis or '<li>(vazio)</li>'}</ul>"

@app.route('/products/add', methods=['POST'])
@login_required
def add_product_route():
    name = request.form.get('name', '').strip()
    sku = request.form.get('sku', '').strip()
    unit = request.form.get('unit', '').strip()
    price = request.form.get('price', '').strip()
    stock = request.form.get('stock', '').strip()

    flash('Produto cadastrado com sucesso!', 'success')
    return redirect(url_for('products'))

# --- SUPPLIERS: atualizar e deletar -----------------------------
@app.route('/update_supplier/<int:supplier_id>', methods=['POST'], endpoint='update_supplier')
@login_required
def update_supplier(supplier_id):
    u = current_user()
    s = Supplier.query.get_or_404(supplier_id)
    # garante que o fornecedor pertence ao usuário logado
    # (se você não tiver user_id em Supplier, remova este if)
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
    # garante que o fornecedor pertence ao usuário logado
    if getattr(s, 'user_id', None) and s.user_id != u.id:
        abort(403)

    db.session.delete(s)
    db.session.commit()
    flash('Fornecedor excluído.', 'info')
    return redirect(url_for('suppliers'))


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

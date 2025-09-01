import os
import re
import secrets
from io import BytesIO
from functools import wraps
from datetime import datetime
from typing import Any, Optional, Callable, cast, Tuple

from dotenv import load_dotenv
from flask import (
    Flask, render_template, render_template_string, request, redirect, url_for,
    session, flash, jsonify, get_flashed_messages, abort, send_file, current_app, g
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from PIL import Image
from sqlalchemy import select, text
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
            flash("Faça login para continuar.", "warning")
            return redirect(url_for('login'))
        g.user = u  # deixa o user no contexto da request
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

def allowed_file(filename: str) -> bool:
    return bool(filename) and '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# injeta user (como dict compatível com user.get(...)) em TODOS os templates
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
            "profile_image": (u.profile_image or "images/user-icon.png"),
        }
    }

# ------------------------------------------------------------------------------
# Páginas Públicas / Auth
# ------------------------------------------------------------------------------
@app.route('/hero')
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

        # aceita e-mail OU username (inclui admin)
        if '@' in login_input:
            user = User.query.filter(User.email == login_input.lower()).first()
        else:
            user = User.query.filter(User.username == login_input).first()
            if not user and login_input.lower() == 'admin':
                user = User.query.filter(User.username == 'admin').first()

        stored_hash = None
        if user:
            stored_hash = getattr(user, 'password_hash', None) or getattr(user, 'password', None)

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
    flash('Você saiu da sua conta.', 'info')
    return redirect(url_for('login'))

@app.route('/privacy_policy')
def privacy_policy():
    return render_template("privacy_policy.html")

@app.route('/about')
def about():
    return render_template("about.html")

# ------------------------------------------------------------------------------
# Rotas principais / Dashboard
# ------------------------------------------------------------------------------
@app.route('/')
@login_required
def index():
    u = current_user()

    total_patients = Patient.query.filter_by(doctor_id=u.id).count()
    total_consults = (
        Consult.query
        .join(Patient, Patient.id == Consult.patient_id)
        .filter(Patient.doctor_id == u.id)
        .count()
    )

    pkg = PackageUsage.query.filter_by(user_id=u.id).first()
    used = int(pkg.used) if pkg and pkg.used is not None else 0
    total = int(pkg.total) if pkg and pkg.total is not None else 0
    remaining = max(total - used, 0)

    return render_template(
        'index.html',
        total_patients=total_patients,
        total_consults=total_consults,
        used=used,
        remaining=remaining,
        package_used=used,
        package_limit=total,
        package_total=total
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
            from mercado_pago import generate_payment_link  # opcional/local
            link = generate_payment_link(pacote, valor)
        except Exception:
            link = None
        return redirect(link or url_for('purchase'))
    # se você tiver purchase.html, ele é usado; senão um fallback simples
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
    default_rel = "images/user-icon.png"

    # caminho relativo salvo no banco (ex.: "uploads/profiles/xxx.jpg" ou "images/user-icon.png")
    rel = (u.profile_image or "").replace("\\", "/")

    if rel and rel != default_rel:
        # monta caminho absoluto dentro de /static
        abs_path = os.path.join(STATIC_DIR, rel)

        # só apaga se estiver dentro de /static/uploads/profiles por segurança
        try:
            allowed_root = os.path.realpath(os.path.join(STATIC_DIR, "uploads", "profiles"))
            abs_norm = os.path.realpath(abs_path)
            if abs_norm.startswith(allowed_root) and os.path.exists(abs_norm):
                os.remove(abs_norm)
        except Exception as e:
            print("[profile_image] remove error:", e)

    # volta para a imagem padrão
    u.profile_image = default_rel
    db.session.commit()
    flash("Foto de perfil removida.", "info")
    return redirect(url_for("account"))

@app.route('/update_personal_info', methods=['POST'], endpoint='update_personal_info')
@login_required
def update_personal_info():
    from datetime import datetime
    import time as _time

    u = current_user()

    # Campos de texto (opcionais)
    name = (request.form.get("name") or "").strip()
    birthdate_str = (request.form.get("birthdate") or "").strip()  # esperado "YYYY-MM-DD"

    if name:
        u.name = name

    if birthdate_str:
        try:
            u.birthdate = datetime.strptime(birthdate_str, "%Y-%m-%d").date()
        except ValueError:
            flash("Data de nascimento inválida. Use o formato AAAA-MM-DD.", "warning")

    # Upload da imagem de perfil (opcional)
    file = request.files.get("profile_image")
    if file and file.filename:
        if not allowed_file(file.filename):
            flash("Tipo de arquivo não permitido. Use png, jpg ou jpeg.", "warning")
            return redirect(url_for("account"))

        # salva dentro de static/uploads/profiles/
        filename = secure_filename(file.filename)
        ext = filename.rsplit(".", 1)[1].lower()

        dest_dir = os.path.join(STATIC_DIR, "uploads", "profiles")
        os.makedirs(dest_dir, exist_ok=True)

        new_name = f"user_{u.id}_{int(_time.time())}.{ext}"
        dest_path = os.path.join(dest_dir, new_name)
        file.save(dest_path)

        # caminho relativo ao /static para usar com url_for('static', filename=...)
        rel_path = os.path.relpath(dest_path, STATIC_DIR).replace("\\", "/")  # "uploads/profiles/xxx.jpg"
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

# ------------------------------------------------------------------------------
# Uploads & PDF (placeholder básico)
# ------------------------------------------------------------------------------
@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        file = request.files.get('file')

        if not file:
            flash('Nenhum arquivo selecionado.', 'warning')
            return redirect(url_for('upload'))

        raw_name = file.filename or ""
        if not raw_name.strip():
            flash('Nenhum arquivo selecionado.', 'warning')
            return redirect(url_for('upload'))

        if not allowed_file(raw_name):
            flash('Tipo de arquivo não permitido.', 'warning')
            return redirect(url_for('upload'))

        filename = secure_filename(raw_name)
        if not filename:
            flash('Nome de arquivo inválido.', 'warning')
            return redirect(url_for('upload'))

        dest = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(dest)

        flash('Arquivo enviado com sucesso.', 'success')
        return redirect(url_for('upload'))

    return render_template('upload.html')

@app.route('/download_pdf/<int:patient_id>')
@login_required
def download_pdf(patient_id):
    u = current_user()
    patient = Patient.query.get_or_404(patient_id)
    if patient.doctor_id != u.id:
        abort(403)

    consults = Consult.query.filter_by(patient_id=patient_id).order_by(Consult.id.asc()).all()
    if consults:
        pdf_bytes = BytesIO(b"%PDF-1.4\n% Ponza Health dummy\n")
        return send_file(pdf_bytes, as_attachment=True, download_name=f"Relatorio_{patient.name}.pdf")
    else:
        flash("Nenhuma consulta encontrada para este paciente.", "info")
        return redirect(url_for('patients'))
    
# ------------------------------------------------------------------------------
# Agenda (tela)
# ------------------------------------------------------------------------------
from jinja2 import TemplateNotFound  # se ainda não importou no topo

@app.route('/agenda', methods=['GET'], endpoint='agenda')
@login_required
def agenda_view():
    try:
        return render_template('agenda.html')
    except TemplateNotFound:
        # fallback simples (só pra não quebrar se o template sumir)
        return """
        <!doctype html><meta charset="utf-8">
        <h1>Agenda</h1>
        <p>Crie o template <code>templates/agenda.html</code>.</p>
        <p><a href="{0}">Voltar</a></p>
        """.format(url_for('index'))
    
# ------------------------------------------------------------------------------
# Agenda (API para criar evento a partir do modal)
# ------------------------------------------------------------------------------
from datetime import timedelta

@app.route('/api/add_event', methods=['POST'])
@login_required
def api_add_event():
    """
    Espera JSON do modal:
      { "title": "...", "start": "YYYY-MM-DDTHH:MM" ou "YYYY-MM-DDT00:00", "notes": "..." }
    Salva como AgendaEvent (ligado ao usuário logado).
    """
    u = current_user()
    data = request.get_json(silent=True) or {}

    title = (data.get('title') or '').strip()
    start_str = (data.get('start') or '').strip()
    # notes é opcional no modelo; se quiser, concatena ao título:
    notes = (data.get('notes') or '').strip()
    if notes:
        title = f"{title} — {notes}" if title else notes

    if not title or not start_str:
        return jsonify(success=False, error="Título e data/hora são obrigatórios."), 400

    # tenta parsear "YYYY-MM-DDTHH:MM" ou "YYYY-MM-DD"
    try:
        # FullCalendar envia "YYYY-MM-DDTHH:MM"
        start_dt = datetime.fromisoformat(start_str)
    except ValueError:
        try:
            # fallback: só data -> assume 00:00
            start_dt = datetime.fromisoformat(start_str + "T00:00")
        except Exception:
            return jsonify(success=False, error="Formato de data/hora inválido."), 400

    # define um fim padrão (1 hora depois) para eventos com hora
    end_dt = start_dt + timedelta(hours=1)

    ev = AgendaEvent(user_id=u.id, title=title, start=start_dt, end=end_dt)
    db.session.add(ev)
    db.session.commit()

    return jsonify(success=True, event_id=ev.id), 201


# ------------------------------------------------------------------------------
# Pacientes / Médicos
# ------------------------------------------------------------------------------
@app.route('/patients')
@login_required
def patients():
    u = current_user()
    items = Patient.query.filter_by(doctor_id=u.id).order_by(Patient.id.desc()).all()
    return render_template('patients.html', patients=items)

@app.route('/patients/new', methods=['GET', 'POST'])
@login_required
def new_patient():
    u = current_user()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        age  = request.form.get('age', '').strip()
        if not name:
            flash('Nome é obrigatório.', 'warning')
            return redirect(url_for('new_patient'))

        p = Patient(name=name, doctor_id=u.id)
        if age.isdigit():
            p.age = int(age)
        db.session.add(p)
        db.session.commit()
        flash('Paciente cadastrado com sucesso.', 'success')
        return redirect(url_for('patients'))

    return render_template('new_patient.html')

@app.route('/doctors')
@login_required
def doctors():
    items = Doctor.query.order_by(Doctor.id.desc()).all()
    return render_template('doctors.html', doctors=items)

# APIs auxiliares
@app.route('/api_doctors')
def api_doctors():
    docs = Doctor.query.order_by(Doctor.name).all()
    return jsonify([{"id": d.id, "name": d.name} for d in docs])

# ------------------------------------------------------------------------------
# Médicos — criar via formulário do doctors.html
# ------------------------------------------------------------------------------
@app.route('/doctors/add', methods=['POST'], endpoint='add_doctor_route')
@login_required
def add_doctor_route():
    """
    Recebe POST do formulário em doctors.html e cria um novo médico.
    Campos esperados no form: name, email, phone, specialty (opcionais).
    Só 'name' é obrigatório.
    """
    name      = (request.form.get('name') or '').strip()
    email     = (request.form.get('email') or '').strip().lower()
    phone     = (request.form.get('phone') or '').strip()
    specialty = (request.form.get('specialty') or '').strip()

    if not name:
        flash('Informe o nome do médico.', 'warning')
        return redirect(url_for('doctors'))

    d = Doctor(name=name)

    # Preenche campos caso existam no modelo
    for attr, val in {
        'email': email or None,
        'phone': phone or None,
        'specialty': specialty or None,
    }.items():
        try:
            setattr(d, attr, val)
        except Exception:
            # Ignora se o atributo não existir no modelo
            pass

    db.session.add(d)
    db.session.commit()
    flash('Médico cadastrado com sucesso!', 'success')
    return redirect(url_for('doctors'))


@app.route('/api/events')
@login_required
def api_events():
    u = current_user()
    doctor_id = request.args.get('doctor_id', type=int)

    events = []
    ag = AgendaEvent.query.filter_by(user_id=u.id).all()
    for e in ag:
        events.append({
            "title": e.title or "Evento",
            "start": e.start.isoformat() if e.start else None,
            "end":   e.end.isoformat() if e.end else None,
            "allDay": False,
        })

    q = Consult.query
    if doctor_id:
        q = q.filter_by(doctor_id=doctor_id)
    consults = q.all()
    for c in consults:
        if c.time:
            start = datetime.combine(c.date, c.time).isoformat()
            events.append({"title": c.notes or "Consulta", "start": start})
        else:
            events.append({"title": c.notes or "Consulta", "start": c.date.isoformat(), "allDay": True})

    return jsonify(events)

# ------------------------------------------------------------------------------
# Catálogo (lista/edita pacientes) — caso seu template use
# ------------------------------------------------------------------------------
@app.route('/catalog')
@login_required
def catalog():
    u = current_user()
    search = request.args.get('search', '').strip().lower()
    status = request.args.get('status', '').strip()

    patients = Patient.query.filter_by(doctor_id=u.id).all()
    if search:
        patients = [p for p in patients if search in (p.name or '').lower()]
    if status:
        patients = [p for p in patients if (p.status or '') == status]

    doctors_list = Doctor.query.order_by(Doctor.name).all()
    return render_template('catalog.html', patients=patients, doctors=doctors_list)

@app.route('/edit_patient/<int:patient_id>', methods=['GET', 'POST'])
@login_required
def edit_patient(patient_id):
    u = current_user()
    patient = Patient.query.get_or_404(patient_id)
    if patient.doctor_id != u.id:
        abort(403)

    if request.method == 'POST':
        patient.name         = request.form['name'].strip()
        patient.age          = int(request.form['age']) if request.form.get('age') else None
        patient.cpf          = request.form['cpf'].strip()
        patient.gender       = request.form['gender'].strip()
        patient.phone        = request.form['phone'].strip()
        patient.prescription = request.form.get('prescription', '').strip()
        patient.status       = request.form.get('status', patient.status).strip()
        db.session.commit()
        return redirect(url_for('catalog'))

    return render_template('edit_patient.html', patient=patient)

@app.route('/patient_result/<int:patient_id>')
@login_required
def patient_result(patient_id):
    u = current_user()
    patient = Patient.query.get_or_404(patient_id)
    if patient.doctor_id != u.id:
        abort(403)

    consults = Consult.query.filter_by(patient_id=patient_id).order_by(Consult.id.asc()).all()
    if consults:
        latest = consults[-1].notes or ""
        parts = latest.split("Prescrição:\n", 1)
        diagnostic_text  = parts[0].strip()
        prescription_text = parts[1].strip() if len(parts) > 1 else patient.prescription or ""
    else:
        diagnostic_text  = "Nenhuma consulta registrada."
        prescription_text = patient.prescription or ""

    return render_template('result.html',
                           patient=patient,
                           diagnostic_text=diagnostic_text,
                           prescription_text=prescription_text,
                           doctor_name=getattr(u, "name", u.username))

@app.route('/patient_info/<int:patient_id>')
@login_required
def patient_info(patient_id):
    u = current_user()
    patient = Patient.query.get_or_404(patient_id)
    if patient.doctor_id != u.id:
        abort(403)
    return render_template('patient_info.html', patient=patient)

@app.route('/api/add_patient', methods=['POST'])
@login_required
def api_add_patient():
    u = current_user()
    data = request.get_json() or {}
    name  = (data.get("name") or "").strip()
    age_s = data.get("age", "")
    cpf   = (data.get("cpf") or "").strip()
    gender= (data.get("gender") or "").strip()
    phone = (data.get("phone") or "").strip()
    prescription = (data.get("prescription") or "").strip()

    if not (name and age_s):
        return jsonify(success=False, error='Preencha todos os campos obrigatórios'), 400
    try:
        age = int(age_s)
    except ValueError:
        return jsonify(success=False, error='Idade inválida'), 400

    p = Patient(name=name, age=age, cpf=cpf or None, gender=gender or None,
                phone=phone or None, doctor_id=u.id, prescription=prescription)
    db.session.add(p)
    db.session.commit()
    return jsonify(success=True, patient_id=p.id), 201

@app.route('/delete_patient/<int:patient_id>', methods=['POST'])
@login_required
def delete_patient(patient_id):
    u = current_user()
    p = Patient.query.get_or_404(patient_id)
    if p.doctor_id != u.id:
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
    if p.doctor_id != u.id:
        abort(403)
    p.status = new_status
    db.session.commit()
    return redirect(url_for('catalog'))

# ------------------------------------------------------------------------------
# Quotes (Cotações) — endpoints usados por templates
# ------------------------------------------------------------------------------
@app.route('/quotes', methods=['GET'], endpoint='quote_index')
@login_required
def quotes_index():
    quotes = Quote.query.order_by(Quote.created_at.desc()).all()
    # usa quotes.html se existir; senão, um fallback simples
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
        supplier_ids = request.form.getlist('supplier_ids')  # checkboxes do HTML

        if not title or not items_raw or not supplier_ids:
            flash('Preencha título, itens e fornecedores.', 'warning')
            return redirect(url_for('create_quote'))

        # Normaliza itens: tenta JSON; se falhar, usa linhas
        try:
            parsed = loads(items_raw)
            if isinstance(parsed, list):
                items_norm = [str(x).strip() for x in parsed if str(x).strip()]
            elif isinstance(parsed, dict):
                items_norm = parsed  # mantém estrutura se for dict
            else:
                items_norm = [str(parsed).strip()]
        except Exception:
            items_norm = [ln.strip() for ln in items_raw.splitlines() if ln.strip()]

        # Normaliza suppliers para JSON (mantém como strings/ids)
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

    # GET: envia fornecedores para o template usado pelo seu HTML
    suppliers = Supplier.query.order_by(Supplier.name.asc()).all()
    try:
        return render_template('quote_new.html', suppliers=suppliers)
    except TemplateNotFound:
        # fallback simples (mantém compatível com os nomes do seu HTML)
        supplier_opts = ''.join(
            f'<label><input type="checkbox" name="supplier_ids" value="{s.id}"> {s.name}</label><br>'
            for s in suppliers
        )
        return render_template_string(f"""
        <h1>Nova Cotação</h1>
        <form method="post">
            <p>Título: <input name="title" required></p>
            <p>Itens (texto ou JSON): <br><textarea name="items" rows="6" cols="60" required></textarea></p>
            <p>Fornecedores:<br>{supplier_opts}</p>
            <button type="submit">Salvar</button>
        </form>
        <p><a href="{{{{ url_for('quote_index') }}}}">Voltar</a></p>
        """)

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

# alias comum em templates: quote_show
app.add_url_rule('/quotes/<int:quote_id>/show', endpoint='quote_show', view_func=quotes_view, methods=['GET'])

@app.route('/quotes/<int:quote_id>/delete', methods=['POST'], endpoint='quote_delete')
@login_required
def quotes_delete(quote_id):
    q = Quote.query.get_or_404(quote_id)
    db.session.delete(q)
    db.session.commit()
    flash('Cotação removida.', 'info')
    return redirect(url_for('quote_index'))

# ------------------------------------------------------------------------------
# Suppliers
# ------------------------------------------------------------------------------
@app.route('/suppliers/add', methods=['POST'], endpoint='add_supplier')
@login_required
def add_supplier():
    u = current_user()
    name  = (request.form.get('name') or '').strip()
    phone = (request.form.get('phone') or '').strip()
    email = (request.form.get('email') or '').strip()

    if not name:
        flash("Nome é obrigatório.", "warning")
        return redirect(url_for('suppliers_index'))

    s = Supplier(user_id=u.id, name=name, phone=phone or None, email=email or None)
    db.session.add(s)
    db.session.commit()

    flash("Fornecedor cadastrado com sucesso!", "success")
    return redirect(url_for('suppliers_index'))

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
    # pegue os campos do form (ajuste nomes conforme seu <input name="...">)
    name = request.form.get('name', '').strip()
    sku = request.form.get('sku', '').strip()
    unit = request.form.get('unit', '').strip()
    price = request.form.get('price', '').strip()
    stock = request.form.get('stock', '').strip()

    # TODO: valide e salve no seu repositório/banco
    # ex: db.add_product(name=name, sku=sku, unit=unit, price=Decimal(price), stock=int(stock))

    flash('Produto cadastrado com sucesso!', 'success')
    return redirect(url_for('products'))

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

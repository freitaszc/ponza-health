from flask import Flask, render_template, request, redirect, url_for, session, make_response, jsonify
from datetime import datetime, timedelta
import os
import json
import secrets
import weasyprint
from prescription import analyze_pdf
from records import (
    add_consultation, add_patient, get_consults, get_patient, get_patients, update_patient,
    delete_patient_record, add_product, get_products, update_product_status, update_doctor,
    update_patient_status, save_products, get_doctors, add_doctor_if_not_exists, get_consults
)
from werkzeug.security import check_password_hash, generate_password_hash
from dotenv import load_dotenv
import jwt
from typing import cast
from whatsapp import enviar_pdf_whatsapp
from mercado_pago import gerar_link_pagamento

# --- CONFIGURAÇÃO INICIAL ---
app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
load_dotenv()

USERNAME = os.getenv("APP_USERNAME")
PASSWORD = os.getenv("APP_PASSWORD")

MUX_TOKEN_ID = os.getenv("MUX_TOKEN_ID")
MUX_TOKEN_SECRET = os.getenv("MUX_TOKEN_SECRET")
MUX_SIGNING_KEY = os.getenv("MUX_SIGNING_KEY")
MUX_PRIVATE_KEY_PATH = os.getenv("MUX_PRIVATE_KEY")

required_env = {
    "MUX_TOKEN_ID": os.getenv("MUX_TOKEN_ID"),
    "MUX_TOKEN_SECRET": os.getenv("MUX_TOKEN_SECRET"),
    "MUX_SIGNING_KEY": os.getenv("MUX_SIGNING_KEY"),
    "MUX_PRIVATE_KEY": os.getenv("MUX_PRIVATE_KEY")
}

missing = [key for key, value in required_env.items() if not value]
if missing:
    raise EnvironmentError(f"As seguintes variáveis de ambiente MUX estão ausentes: {', '.join(missing)}")

token_id = required_env["MUX_TOKEN_ID"]
token_secret = required_env["MUX_TOKEN_SECRET"]
signing_key = required_env["MUX_SIGNING_KEY"]
mux_key_content = required_env["MUX_PRIVATE_KEY"]
if mux_key_content:
    os.makedirs("Keys", exist_ok=True)
    private_key_path = "Keys/mux_private.key"
    with open(private_key_path, "w") as f:
        f.write(mux_key_content.replace("\\n", "\n"))
else:
    raise EnvironmentError("MUX_PRIVATE_KEY está ausente ou inválida.")

# --- AUTENTICAÇÃO ---
def load_users():
    with open('json/users.json', 'r', encoding='utf-8') as f:
        return json.load(f)

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/privacy-policy')
def privacy_policy():
    return render_template('privacy_policy.html')

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        users = load_users()
        user = next((u for u in users if u['username'] == username), None)
        if user and check_password_hash(user['password'], password):
            session['user'] = username
            return redirect(url_for('index'))
        return render_template('login.html', error='Credenciais inválidas')
    return render_template('login.html')

@app.route('/update_personal_info', methods=['POST'])
def update_personal_info():
    if 'user' not in session:
        return redirect(url_for('login'))

    users = load_users()
    user = next((u for u in users if u['username'] == session['user']), None)

    if not user:
        return "Usuário não encontrado", 404

    firstname = request.form.get("name", "")
    secondname = request.form.get("secondname", "")
    birthdate = request.form.get("birthdate", "")
    email = request.form.get("email", "")

    user["name"] = f"{firstname.strip()} {secondname.strip()}"
    user["birthdate"] = birthdate
    user["email"] = email

    profile_image = request.files.get("profile_image")
    if profile_image and profile_image.filename:
        uploads_folder = os.path.join("static", "profile_images")
        os.makedirs(uploads_folder, exist_ok=True)
        image_filename = f"{session['user']}_profile.png"
        image_path = os.path.join(uploads_folder, image_filename)
        profile_image.save(image_path)
        user["profile_image"] = f"profile_images/{image_filename}"

    with open('json/users.json', 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=2, ensure_ascii=False)

    return redirect(url_for("account"))

@app.route('/update_password', methods=['POST'])
def update_password():
    if 'user' not in session:
        return redirect(url_for('login'))

    users = load_users()
    user = next((u for u in users if u['username'] == session['user']), None)

    if not user:
        return "Usuário não encontrado", 404

    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not check_password_hash(user['password'], current_password):
        return render_template("account.html", user=user, error="Senha atual incorreta.")

    if new_password != confirm_password:
        return render_template("account.html", user=user, error="As senhas não coincidem.")

    user['password'] = generate_password_hash(new_password)

    with open('json/users.json', 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=2, ensure_ascii=False)

    return redirect(url_for("account"))

@app.route('/payment', methods=['POST'])
def payment():
    if 'user' not in session:
        return redirect(url_for('login'))

    return redirect(url_for("account"))

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

# --- DASHBOARD INICIAL ---
@app.route('/index')
def index():
    if 'user' not in session:
        return redirect(url_for('login'))

    file_path = os.path.join(os.path.dirname(__file__), 'json', 'consults.json')
    with open(file_path, encoding="utf-8") as f:
        consults = json.load(f)

    counts = {}
    for consultas in consults.values():
        for consulta in consultas:
            lines = consulta.splitlines()
            for line in lines:
                if "Data:" in line:
                    date_str = line.split("Data:")[1].strip()
                    try:
                        date_obj = datetime.strptime(date_str, "%d-%m-%Y")
                        date_obj = date_obj.replace(hour=0, minute=0, second=0, microsecond=0)
                        counts[date_obj] = counts.get(date_obj, 0) + 1
                    except ValueError:
                        continue

    today = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    chart_data = []
    total = 0
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        count = counts.get(day, 0)
        total += count
        dias_passados = 7 - i
        media_acumulada = round(total / dias_passados, 2)
        chart_data.append({
            "date": day.strftime("%d/%m"),
            "count": count,
            "media": media_acumulada
        })

    users = load_users()
    user_data = next((u for u in users if u['username'] == session['user']), {})
    full_name = user_data.get('name', session['user'])
    return render_template("index.html", chart_data=chart_data, username=full_name, user=user_data)

# --- BioO3 Lab E PROCESSAMENTO ---
@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if 'user' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        pdf_file = request.files.get('pdf_file')
        if not pdf_file or pdf_file.filename == '':
            return render_template('upload.html', error='Por favor, selecione um arquivo PDF.')
        
        # Salva o PDF original na pasta uploads
        uploads_folder = os.path.join("static", "uploads")
        os.makedirs(uploads_folder, exist_ok=True)

        filename = pdf_file.filename or "arquivo.pdf"
        upload_path = os.path.join(uploads_folder, filename)
        pdf_file.save(upload_path)

        # Processamento do PDF
        diagnostic, prescription, name, gender, age, cpf, phone, doctor_name = analyze_pdf(upload_path)
        print("[DEBUG] Médico extraído:", doctor_name)
        doctor_id, doctor_phone = add_doctor_if_not_exists(doctor_name)
        patient_id = add_patient(name, age, cpf, gender, phone, doctor_id, prescription)
        today = datetime.today().strftime('%d-%m-%Y')

        add_consultation(patient_id, f"Data: {today}\n\nDiagnóstico:\n{diagnostic}\n\nPrescrição:\n{prescription}")

        patient_info = f"Paciente: {name}\nIdade: {age}\nCPF: {cpf}\nSexo: {gender}\nTelefone: {phone}\nMédico: {doctor_name}"
        session['diagnostic_text'] = diagnostic
        session['prescription_text'] = prescription
        session['doctor_name'] = doctor_name
        session['patient_info'] = patient_info

        # --- DEBUG: Verificar os dados antes de gerar o PDF ---
        print("[DEBUG] Dados no momento da geração do PDF:")
        print("diagnostic:\n", diagnostic)
        print("prescription:\n", prescription)
        print("doctor_name:\n", doctor_name)
        print("patient_info:\n", patient_info)
        print("[DEBUG] Fim dos dados\n")

        html = render_template(
            "result_pdf.html",
            diagnostic_text=diagnostic,
            prescription_text=prescription,
            doctor_name=doctor_name,
            patient_info=patient_info,
            logo_path=os.path.join(app.root_path, 'static', 'images', 'logo.png')
        )
        pdf = weasyprint.HTML(string=html, base_url=os.path.join(app.root_path, 'static')).write_pdf()

        if not isinstance(pdf, bytes):
            raise ValueError("Erro ao gerar PDF: resultado não é do tipo bytes.")

        cpf_limpo = (cpf or "").replace('.', '').replace('-', '')
        pdf_filename = f"resultado_{cpf_limpo}.pdf"
        output_folder = os.path.join("static", "output")
        os.makedirs(output_folder, exist_ok=True)
        pdf_path_publico = os.path.join(output_folder, pdf_filename)

        with open(pdf_path_publico, 'wb') as f:
            f.write(pdf)

        # Gerar os links corretos
        pdf_link_analisado = url_for('static', filename=f"output/{pdf_filename}", _external=True)
        pdf_link_original = url_for('static', filename=f"uploads/{pdf_file.filename}", _external=True)

        status_envio = enviar_pdf_whatsapp(
            medico_nome=doctor_name,
            paciente_nome=name,
            pdf_link_analisado=pdf_link_analisado,
            pdf_link_original=pdf_link_original
        )

        if status_envio:
            print("[WHATSAPP] Erro ao enviar mensagem:", status_envio)
        else:
            print(f"[WHATSAPP] Mensagem enviada com sucesso para {doctor_name}.")


        return render_template(
            'result.html',
            diagnostic_text=diagnostic,
            prescription_text=prescription
        )

    return render_template('upload.html')

@app.route("/download_pdf")
def download_pdf():
    if 'user' not in session:
        return redirect(url_for('login'))

    diagnostic_text = session.get('diagnostic_text', '')
    prescription_text = session.get('prescription_text', '')
    doctor_name = session.get('doctor_name', '')
    patient_info = session.get('patient_info', '')

    logo_path = os.path.join(app.root_path, 'static', 'images', 'logo.png')
    html = render_template(
        "result_pdf.html",
        diagnostic_text=diagnostic_text,
        prescription_text=prescription_text,
        doctor_name=doctor_name,
        patient_info=patient_info,
        logo_path=logo_path
    )

    base_path = os.path.join(app.root_path, 'static')
    pdf = weasyprint.HTML(string=html, base_url=base_path).write_pdf()

    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'attachment; filename=prescription.pdf'
    return response

# --- PACIENTES ---
@app.route('/catalog')
def catalog():
    if 'user' not in session:
        return redirect(url_for('login'))

    search = request.args.get('search', '').lower()
    status_filter = request.args.get('status', '')
    patients = get_patients()
    doctors = get_doctors()

    def match(p):
        return (not search or search in p.name.lower()) and (not status_filter or p.status == status_filter)

    filtered_patients = [p for p in patients if match(p)]
    return render_template('catalog.html', patients=filtered_patients, doctors=doctors)

@app.route('/edit_patient/<int:patient_id>', methods=['GET', 'POST'])
def edit_patient(patient_id):
    if 'user' not in session:
        return redirect(url_for('login'))
    patient = get_patient(patient_id)
    if not patient:
        return "Paciente não encontrado", 404
    doctors = get_doctors()

    if request.method == 'POST':
        update_patient(
            patient_id,
            request.form['name'],
            request.form['age'],
            request.form['cpf'],
            request.form['gender'],
            request.form['phone'],
            int(request.form['doctor']),
            request.form.get('prescription', '').strip() 
        )
        return redirect(url_for('catalog'))

    return render_template('edit_patient.html', patient=patient, doctors=doctors)

@app.route('/patient_result/<int:patient_id>')
def patient_result(patient_id):
    if 'user' not in session:
        return redirect(url_for('login'))

    patient = get_patient(patient_id)
    if not patient:
        return render_template('result.html', result_text="Paciente não encontrado.")

    consultations = get_consults(patient_id)
    if not consultations:
        return render_template(
            'result.html',
            diagnostic_text="Nenhuma consulta cadastrada.",
            prescription_text="",
            doctor_name=patient.get("doctor", "Desconhecido")
        )

    latest = consultations[-1]  # texto completo
    parts = latest.split("Prescrição:\n")

    diagnostic_text = parts[0].strip() if len(parts) > 0 else ""
    prescription_text = parts[1].strip() if len(parts) > 1 else ""

    return render_template(
        'result.html',
        diagnostic_text=diagnostic_text,
        prescription_text=prescription_text,
        doctor_name=patient.get("doctor", "Desconhecido")
    )

@app.route('/delete_patient/<int:patient_id>', methods=['POST'])
def delete_patient(patient_id):
    if 'user' not in session:
        return redirect(url_for('login'))
    delete_patient_record(patient_id)
    return redirect(url_for('catalog'))

# --- CONSULTAS ---
@app.route('/add_consultation/<int:patient_id>', methods=['GET', 'POST'])
def add_consultation_route(patient_id):
    if 'user' not in session:
        return redirect(url_for('login'))

    patient = get_patient(patient_id)
    if not patient:
        return "Paciente não encontrado", 404

    if request.method == 'POST':
        data = request.form['date']
        notes = request.form.get('notes', '')
        try:
            data_obj = datetime.strptime(data, '%d/%m/%Y')
            datetime_str = data_obj.strftime('%Y-%m-%dT00:00:00')
        except ValueError:
            return "Data inválida. Use o formato dd/mm/aaaa.", 400

        events = load_agenda()
        events.append({
            'title': f"Consulta - {patient['name']}",
            'datetime': datetime_str,
            'notes': notes
        })
        save_agenda(events)
        return redirect(url_for('agenda'))

    return render_template('add_consultation.html', patients=[patient])

@app.route('/submit_consultation', methods=['POST'])
def submit_consultation():
    if 'user' not in session:
        return redirect(url_for('login'))

    data = request.form['date']
    notes = request.form.get('notes', '')
    patient_id = request.form.get('patient')

    try:
        data_obj = datetime.strptime(data, '%d/%m/%Y')
        datetime_str = data_obj.strftime('%Y-%m-%dT00:00:00')
    except ValueError:
        return "Data inválida. Use o formato dd/mm/aaaa.", 400

    title = "Consulta Geral"
    if patient_id:
        try:
            patient = get_patient(int(patient_id))
            if patient:
                title = f"Consulta - {patient['name']}"
        except Exception:
            pass

    events = load_agenda()
    events.append({
        'title': title,
        'datetime': datetime_str,
        'notes': notes
    })
    save_agenda(events)

    return redirect(url_for('agenda'))

@app.route('/add_general_consultation', methods=['POST'])
def add_general_consultation():
    if 'user' not in session:
        return jsonify({'error': 'Não autenticado'}), 403

    data = request.get_json()
    date_str = data.get('date', '')
    notes = data.get('notes', '')
    patient_id = data.get('patient_id')

    try:
        date_obj = datetime.strptime(date_str, '%d/%m/%Y')
        datetime_str = date_obj.strftime('%Y-%m-%dT00:00:00')
    except ValueError:
        return jsonify({'error': 'Data inválida. Use o formato dd/mm/aaaa.'}), 400

    title = "Consulta Geral"
    if patient_id:
        try:
            patient = get_patient(int(patient_id))
            if patient:
                title = f"Consulta - {patient['name']}"
        except Exception:
            pass

    events = load_agenda()
    events.append({
        'title': title,
        'datetime': datetime_str,
        'notes': notes
    })
    save_agenda(events)

    return jsonify({'success': True})

@app.route('/modal_consultation')
def modal_consultation():
    if 'user' not in session:
        return redirect(url_for('login'))
    patients = get_patients()
    return render_template('add_consultation.html', patients=patients)

# --- PRODUTOS ---
@app.route('/products')
def products():
    if 'user' not in session:
        return redirect(url_for('login'))

    produtos = get_products()
    cat = request.args.get('category', '')
    via = request.args.get('application_route', '')
    stat = request.args.get('status', '')
    stock_f = request.args.get('stock_filter', 'all')
    search = request.args.get('search', '').lower()

    def keep(p):
        return (
            (not cat or p.get('category') == cat) and
            (not via or p.get('application_route') == via) and
            (not stat or p.get('status') == stat) and
            (stock_f != 'in_stock' or p.get('quantity', 0) > 0) and
            (stock_f != 'min_stock' or p.get('quantity', 0) <= p.get('min_stock', 0)) and
            (not search or search in p.get('name', '').lower())
        )

    filtered = [p for p in produtos if keep(p)]
    categories = sorted({p.get('category','') for p in produtos if p.get('category')})
    application_routes = sorted({p.get('application_route','') for p in produtos if p.get('application_route')})

    return render_template('products.html', products=filtered, categories=categories, application_routes=application_routes)

@app.route('/add_product', methods=['POST'])
def add_product_route():
    if 'user' not in session:
        return redirect(url_for('login'))

    name = request.form.get('name', '').strip()
    quantity = int(request.form.get('quantity', 0))
    purchase_price = float(request.form.get('purchase_price', 0))
    sale_price = float(request.form.get('sale_price', 0))

    if not name:
        return "Nome do produto é obrigatório.", 400

    add_product(name, purchase_price, sale_price, quantity)
    return redirect(url_for('products'))

@app.route('/toggle_product_status/<int:product_id>/<new_status>')
def toggle_product_status(product_id, new_status):
    update_product_status(product_id, new_status)
    return redirect(url_for('products'))

@app.route('/toggle_patient_status/<int:patient_id>/<new_status>')
def toggle_patient_status(patient_id, new_status):
    update_patient_status(patient_id, new_status)
    return redirect(url_for('catalog'))

@app.route('/stock_view/<int:product_id>')
def stock_view(product_id):
    product = next((p for p in get_products() if p['id'] == product_id), None)
    if not product:
        return "Produto não encontrado", 404
    return render_template('stock_view.html', product=product)

@app.route('/stock_edit/<int:product_id>', methods=['GET','POST'])
def stock_edit(product_id):
    produtos = get_products()
    product = next((p for p in produtos if p['id'] == product_id), None)
    if not product:
        return "Produto não encontrado", 404
    if request.method == 'POST':
        product['code'] = request.form['code']
        product['name'] = request.form['name']
        product['quantity'] = int(request.form['quantity'])
        product['purchase_price'] = float(request.form['purchase_price'])
        product['sale_price'] = float(request.form['sale_price'])
        save_products(produtos)
        return redirect(url_for('products'))
    return render_template('stock_edit.html', product=product)

@app.route('/delete_product/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    produtos = [p for p in get_products() if p['id'] != product_id]
    save_products(produtos)
    return redirect(url_for('products'))


# --- AGENDA ---
AGENDA_FILE = 'json/agenda.json'

def load_agenda():
    if os.path.exists(AGENDA_FILE):
        with open(AGENDA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def save_agenda(events):
    with open(AGENDA_FILE, 'w', encoding='utf-8') as f:
        json.dump(events, f, ensure_ascii=False, indent=2)

@app.route('/agenda')
def agenda():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('agenda.html')

@app.route('/api/events')
def api_events():
    events = load_agenda()
    calendar_events = [
        {
            "title": event["title"],
            "start": event["datetime"],
            "end": event["datetime"],
            "description": event["notes"]
        } for event in events
    ]
    return jsonify(calendar_events)


# --- API AJAX ---
@app.route('/api/add_patient', methods=['POST'])
def api_add_patient():
    if 'user' not in session:
        return jsonify({'error': 'Não autenticado'}), 403
    data = request.get_json()
    patient_id = add_patient(
        data.get("name", "").strip(),
        int(data.get("age", 0)),
        data.get("cpf", ""),
        data.get("gender", ""),
        data.get("phone", ""),
        int(data.get("doctor", 0)),
        data.get("prescription", "").strip()
    )
    return jsonify({'success': True, 'patient_id': patient_id})

@app.route('/api/doctors')
def api_doctors():
    if 'user' not in session:
        return jsonify({'error': 'Não autenticado'}), 403
    return jsonify(get_doctors())


# --- VÍDEOS MUX ---
VIDEOS_FILE = 'json/videos.json'

def get_videos():
    if os.path.exists(VIDEOS_FILE):
        with open(VIDEOS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def create_signed_token(playback_id: str) -> str:
    from jwt import encode
    with open(private_key_path, 'r') as f:
        private_key = f.read()
    payload = {
        "exp": datetime.utcnow() + timedelta(hours=1),
        "kid": signing_key,
        "aud": "v",
        "sub": playback_id
    }
    token = encode(payload, private_key, algorithm="RS256")
    return token.decode("utf-8") if isinstance(token, bytes) else token

@app.route('/videos')
def videos():
    if 'user' not in session:
        return redirect(url_for('login'))
    raw_videos = get_videos()
    videos = [
        {
            "title": v["title"],
            "playback_id": v["playback_id"],
            "token": create_signed_token(v["playback_id"])
        }
        for v in raw_videos
    ]
    return render_template('videos.html', videos=videos)

@app.route('/watch/<playback_id>')
def watch_video(playback_id):
    videos = get_videos()
    video = next((v for v in videos if v["playback_id"] == playback_id), None)
    if not video:
        return "Vídeo não encontrado", 404

    token = create_signed_token(playback_id)
    pdf_filename = video.get("pdf")  # pode ser None

    return render_template(
        'watch_video.html',
        title=video["title"],
        playback_id=playback_id,
        token=token,
        pdf_filename=pdf_filename
    )

# --- UTILITÁRIOS ---
def send_pdf_to_doctor(phone_number, pdf_path):
    print(f"[ENVIO] Enviando PDF para o número {phone_number}... (simulação)")

@app.route('/api/add_event', methods=['POST'])
def api_add_event():
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'Não autenticado'}), 403

    data = request.get_json()
    title = data.get('title', '').strip()
    datetime_str = data.get('start', '').strip()
    notes = data.get('notes', '').strip()

    if not title or not datetime_str:
        return jsonify({'success': False, 'error': 'Título e data são obrigatórios.'})

    events = load_agenda()
    events.append({
        'title': title,
        'datetime': datetime_str,
        'notes': notes
    })
    save_agenda(events)

    return jsonify({'success': True})

@app.route("/doctors")
def doctors():
    doctors = get_doctors()
    return render_template("doctors.html", doctors=doctors)

@app.route("/update_doctor/<int:doctor_id>", methods=["POST"])
def update_doctor_route(doctor_id):
    update_doctor(doctor_id, request.form["name"], request.form["phone"])
    return redirect(url_for("doctors"))

@app.route('/add_doctor', methods=['POST'])
def add_doctor_route():
    name = request.form['name']
    phone = request.form['phone']
    doctors = get_doctors()
    new_id = max((d['id'] for d in doctors), default=0) + 1
    doctors.append({'id': new_id, 'name': name, 'phone': phone})
    with open('json/doctors.json', 'w', encoding='utf-8') as f:
        json.dump(doctors, f, ensure_ascii=False, indent=2)
    return redirect(url_for('doctors'))

@app.route('/edit_doctor/<int:doctor_id>', methods=['GET', 'POST'])
def edit_doctor(doctor_id):
    doctors = get_doctors()
    doctor = next((d for d in doctors if d['id'] == doctor_id), None)
    if not doctor:
        return "Médico não encontrado", 404
    if request.method == 'POST':
        doctor['name'] = request.form['name']
        doctor['phone'] = request.form['phone']
        with open('json/doctors.json', 'w', encoding='utf-8') as f:
            json.dump(doctors, f, indent=4, ensure_ascii=False)
        return redirect(url_for('doctors'))
    return render_template('edit_doctor.html', doctor=doctor)

@app.route("/account")
def account():
    if 'user' not in session:
        return redirect(url_for('login'))

    users = load_users()
    user = next((u for u in users if u['username'] == session['user']), None)
    if not user:
        return "Usuário não encontrado", 404

    return render_template("account.html", user=user)

@app.route('/remove_profile_image', methods=['POST'])
def remove_profile_image():
    if 'user' not in session:
        return redirect(url_for('login'))

    users = load_users()
    user = next((u for u in users if u['username'] == session['user']), None)

    if not user:
        return "Usuário não encontrado", 404

    # Remove a imagem do sistema
    if user.get('profile_image') and user['profile_image'] != 'images/user-icon.png':
        image_path = os.path.join("static", user['profile_image'])
        if os.path.exists(image_path):
            os.remove(image_path)
    
    # Reseta para o padrão
    user['profile_image'] = 'images/user-icon.png'

    with open('json/users.json', 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=2, ensure_ascii=False)

    return redirect(url_for('account'))

# --- PAGAMENTO ---

from mercado_pago import gerar_link_pagamento

@app.route('/purchase', methods=['GET', 'POST'])
def purchase():
    try:
        if request.method == 'POST':
            pacote = request.form.get('package')
            valor = {'500': 500, '1500': 1250, '3000': 2125}.get(pacote or "")

            if not valor:
                print("[DEBUG] Pacote inválido selecionado:", pacote)
                return redirect(url_for('purchase'))

            # Gera link de pagamento no Mercado Pago (Checkout Pro)
            link_pagamento = gerar_link_pagamento(pacote, valor)
            if link_pagamento:
                print("[DEBUG] Link de pagamento gerado com sucesso:", link_pagamento)
                return redirect(link_pagamento)
            else:
                print("[DEBUG] Erro ao gerar link de pagamento (link vazio)")
                return redirect(url_for('pagamento_falha'))

        # Sempre envie a variável user, mesmo que vazia (para evitar erro no template)
        return render_template('purchase.html', user={})

    except Exception as e:
        print("[ERRO NA ROTA /purchase]", str(e))
        return redirect(url_for('pagamento_falha'))

@app.route('/pagamento-sucesso')
def pagamento_sucesso():
    return "Pagamento realizado com sucesso."

@app.route('/pagamento-falha')
def pagamento_falha():
    return "Pagamento não foi concluído."

@app.route('/pagamento-pendente')
def pagamento_pendente():
    return "Pagamento em análise. Aguarde a confirmação."

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid payload'}), 400

    print("[Webhook recebido]", data)
    return jsonify({'status': 'received'}), 200

@app.before_request
def proteger_rotas_admin():
    if request.path.startswith(('/purchase', '/webhook', '/api/')) and 'user' not in session:
        return redirect(url_for('login'))

# --- EXECUÇÃO ---
if __name__ == '__main__':
    app.run()

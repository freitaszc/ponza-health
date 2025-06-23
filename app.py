from flask import Flask, render_template, request, redirect, url_for, session, make_response, jsonify
from datetime import datetime, timedelta
import os
import json
import secrets
import weasyprint
from prescription import analyze_pdf
from records import (
    add_consultation, add_patient, get_consults, get_patient, get_patients, update_patient,
    delete_patient_record, add_product, get_products, update_product_status,
    update_patient_status, save_products, get_doctors, add_doctor_if_not_exists, get_consults
)
from werkzeug.security import check_password_hash
from dotenv import load_dotenv
import jwt
from typing import cast
from whatsapp import enviar_pdf_whatsapp


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

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))


# --- DASHBOARD INICIAL ---
@app.route('/index')
def index():
    if 'user' not in session:
        return redirect(url_for('login'))

    pacientes = get_patients()
    produtos = get_products()
    agenda = load_agenda()

    total_pdfs_analisados = sum(len(get_consults(p.id)) for p in pacientes)

    return render_template(
        "index.html",
        produtos=produtos,
        agenda=agenda,
        now=datetime.now(),
        total_pdfs_analisados=total_pdfs_analisados
    )

# --- BioO3 Lab E PROCESSAMENTO ---
@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if 'user' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        pdf_file = request.files.get('pdf_file')
        if not pdf_file or pdf_file.filename == '':
            return render_template('upload.html', error='Por favor, selecione um arquivo PDF.')
        temp_pdf_path = f"/tmp/{pdf_file.filename}"
        pdf_file.save(temp_pdf_path)

        diagnostic, prescription, name, gender, age, cpf, phone, doctor_name = analyze_pdf(temp_pdf_path)
        doctor_id, doctor_phone = add_doctor_if_not_exists(doctor_name)
        patient_id = add_patient(name, age, cpf, gender, phone, doctor_id)
        today = datetime.today().strftime('%d-%m-%Y')

        add_consultation(patient_id, f"Data: {today}\n\nDiagnóstico:\n{diagnostic}\n\nPrescrição:\n{prescription}")

        patient_info = f"Paciente: {name}\nIdade: {age}\nCPF: {cpf}\nSexo: {gender}\nTelefone: {phone}\nMédico: {doctor_name}"
        session['diagnostic_text'] = diagnostic
        session['prescription_text'] = prescription
        session['doctor_name'] = doctor_name
        session['patient_info'] = patient_info

        html = render_template(
            "result_pdf.html",
            diagnostic_text=diagnostic,
            prescription_text=prescription,
            doctor_name=doctor_name,
            patient_info=patient_info
        )
        pdf = weasyprint.HTML(string=html, base_url=request.url_root).write_pdf()
        if not isinstance(pdf, bytes):
            raise ValueError("Erro ao gerar PDF: resultado não é do tipo bytes.")

        temp_pdf_result_path = f"/tmp/resultado_{cpf.replace('.', '').replace('-', '')}.pdf"
        with open(temp_pdf_result_path, 'wb') as f:
            f.write(pdf)

        # Enviar automaticamente para WhatsApp
        temp_pdf_original_path = temp_pdf_path
        if doctor_name:
            status_envio = enviar_pdf_whatsapp(doctor_name, temp_pdf_result_path, temp_pdf_original_path)
            print("[WHATSAPP] Status:", status_envio)

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

    html = render_template(
        "result_pdf.html",
        diagnostic_text=diagnostic_text,
        prescription_text=prescription_text,
        doctor_name=doctor_name,
        patient_info=patient_info
    )
    pdf = weasyprint.HTML(string=html, base_url=request.url_root).write_pdf()
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
            int(request.form['doctor'])
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
        result_text = f"Paciente: {patient['name']}\n\nNenhuma consulta cadastrada."
    else:
        latest = consultations[-1]
        result_text = f"""
Paciente: {patient["name"]}
Idade: {patient["age"]}
CPF: {patient["cpf"]}
Sexo: {patient["gender"]}
Telefone: {patient["phone"]}

Última consulta:

{latest}
"""
    session['doctor_name'] = patient.get("doctor_name", "")
    return render_template('result.html', result_text=result_text)

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
        int(data.get("doctor", 0))
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
    return render_template('watch_video.html', title=video["title"], playback_id=playback_id, token=token)


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

# --- EXECUÇÃO ---
if __name__ == '__main__':
    app.run(debug=True)

# app.py

from fastapi import FastAPI
from pydantic import BaseModel
from typing import List
from records import (
    add_patient, get_patients, get_patient,
    add_consultation, get_consults
)
from prescription import read_pdf  # supondo que já exista
from prescription import analyze_pdf  # se não existir, criaremos depois

from datetime import datetime

app = FastAPI()

# MODELOS PARA A API

class PatientRequest(BaseModel):
    name: str
    age: int
    cpf: str
    phone: str

class ConsultationRequest(BaseModel):
    patient_id: int
    date: str
    diagnostic: str
    prescription: str

class ProcessPDFRequest(BaseModel):
    pdf_path: str
    name: str
    birth_date: str  # vamos armazenar como "idade" = 0 só para simplificar no add_patient

# ROTAS

# GET /patients → lista todos os pacientes
@app.get("/patients")
def list_patients():
    patients = get_patients()
    return [vars(patient) for patient in patients]

# POST /patients → cadastra novo paciente
@app.post("/patients")
def create_patient(patient_request: PatientRequest):
    patient = add_patient(
        patient_request.name,
        patient_request.age,
        patient_request.cpf,
        patient_request.phone
    )
    return vars(patient)

# GET /patients/{id} → paciente + histórico de consultas
@app.get("/patients/{patient_id}")
def get_patient_with_history(patient_id: int):
    patient = get_patient(patient_id)
    if patient is None:
        return {"error": "Patient not found"}

    consultations = get_consults(patient_id)

    return {
        "patient": vars(patient),
        "consultations": [vars(consultation) for consultation in consultations]
    }

# POST /consultations → cadastra nova consulta manual
@app.post("/consultations")
def create_consultation(consultation_request: ConsultationRequest):
    consultation = add_consultation(
        consultation_request.patient_id,
        consultation_request.date,
        consultation_request.diagnostic,
        consultation_request.prescription
    )
    return vars(consultation)

# POST /process_pdf → fluxo automático: cria paciente + consulta com receita
@app.post("/process_pdf")
def process_pdf(request: ProcessPDFRequest):
    # 1. Ler e analisar o PDF
    text = read_pdf(request.pdf_path)
    diagnostic, prescription = analyze_pdf(text)

    # 2. Criar paciente (idade=0 por simplificação, pois só temos birth_date em string)
    patient = add_patient(
        name=request.name,
        age=0,
        cpf="",
        phone=""
    )

    # 3. Criar consulta associada com a receita
    today = datetime.today().strftime('%Y-%m-%d')

    consultation = add_consultation(
        patient.id,
        today,
        diagnostic,
        prescription
    )

    return {
        "patient": vars(patient),
        "consultation": vars(consultation)
    }

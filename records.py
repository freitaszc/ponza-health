patients_db = []
consultations_db =[]

def next_patient_id():
    return len(patients_db) + 1

def next_consultation_id():
    return len(consultations_db) + 1

class Patient:
    def __init__(self, name, age, cpf, phone):
        self.id = next_patient_id()
        self.name = name
        self.age = age
        self.cpf = cpf
        self.phone = phone

class Consult:
    def __init__(self, patient_id, date, diagnostic, prescription):
        self.id = next_consultation_id()
        self.patient_id = patient_id
        self.date = date
        self.diagnostic = diagnostic
        self.prescription = prescription

def add_patient(name, age, cpf, phone):
    patient = Patient(name, age, cpf, phone)
    patients_db.append(patient)
    return patient

def get_patients():
    return patients_db

def get_patient(patient_id):
    for patient in patients_db:
        if patient.id == patient_id:
            return patient
    return None

def add_consultation(patient_id, date, diagnostic, prescription):
    consultation = Consult(patient_id, date, diagnostic, prescription)
    consultations_db.append(consultation)
    return consultation

def get_consults(patient_id):
    return [consultation for consultation in consultations_db if consultation.patient_id == patient_id]
import os
import re
import json
from datetime import datetime
from PyPDF2 import PdfReader


def read_pdf(file_path):
    try:
        reader = PdfReader(file_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return lines

    except Exception as e:
        print(f"Error reading PDF: {e}")
        return []


def read_references(references_path):
    try:
        with open(references_path, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception as e:
        print(f"Error reading references: {e}")
        return None


def parse_min_max(ideal_text):
    try:
        ideal_text = ideal_text.strip().split('\n')[0]

        match = re.match(r"(≥|>=|>)\s*([0-9]+(?:[.,][0-9]+)?)", ideal_text)
        if match:
            return float(match.group(2).replace(",", ".")), float("inf")

        match = re.match(r"(≤|<=|<)\s*([0-9]+(?:[.,][0-9]+)?)", ideal_text)
        if match:
            return float("-inf"), float(match.group(2).replace(",", "."))

        match = re.search(r"([0-9]+(?:[.,][0-9]+)?)\s*[-–]\s*([0-9]+(?:[.,][0-9]+)?)", ideal_text)
        if match:
            return float(match.group(1).replace(",", ".")), float(match.group(2).replace(",", "."))

        match = re.search(r"([0-9]+(?:[.,][0-9]+)?)", ideal_text)
        if match:
            value = float(match.group(1).replace(",", "."))
            return value, value

        return None, None
    except:
        return None, None


def extract_patient_info(lines):
    name, gender, birth_date, cpf, phone, doctor = "", "", "", "", "", ""
    age = 0

    for line in lines:
        if line.startswith("Paciente "):
            name = line.replace("Paciente ", "").strip()

        if line.startswith("Médico"):
            doctor = re.split(r"\s+RG|\s+Prontuário", line.replace("Médico", "").strip(), maxsplit=1)[0].strip()

        cpf_match = re.search(r'CPF\s+(\d{3}\.\d{3}\.\d{3}-\d{2})', line)
        if cpf_match:
            cpf = cpf_match.group(1)

        match = re.search(r"Sexo\s+([MF])\s+Dt nasc\. (\d{2}/\d{2}/\d{4})", line)
        if match:
            gender, birth_date = match.groups()
            try:
                birth_date_dt = datetime.strptime(birth_date, "%d/%m/%Y")
                today = datetime.today()
                age = today.year - birth_date_dt.year - ((today.month, today.day) < (birth_date_dt.month, birth_date_dt.day))
            except:
                age = 0

    return name, gender, age, cpf, phone, doctor


def scan_results(lines, references, gender):
    results = {}
    for test_name, info in references.items():
        synonyms = [s.lower() for s in info.get("synonyms", [])] + [test_name.lower()]
        for line in lines:
            if any(term in line.lower() for term in synonyms):
                match = re.search(r"([0-9]+(?:[.,][0-9]+)?)", line)
                value = float(match.group(1).replace(",", ".")) if match else None
                ideal = info.get("ideal", {}).get(gender) if isinstance(info.get("ideal"), dict) else info.get("ideal")
                min_val, max_val = parse_min_max(str(ideal))
                meds = []
                if value is not None and min_val is not None:
                    if value < min_val:
                        meds = info.get("medications", {}).get("low", [])
                    elif max_val is not None and value > max_val:
                        meds = info.get("medications", {}).get("high", [])

                results[test_name] = {
                    "value": value,
                    "line": line.strip(),
                    "ideal": ideal,
                    "medications": meds
                }
                break
        else:
            results[test_name] = {"value": None, "line": None, "ideal": None, "medications": []}
    return results


def analyze_pdf(file_path, references_path="json/references.json"):
    lines = read_pdf(file_path)
    references = read_references(references_path)

    if not lines or not references:
        return "Error reading PDF or references.", "", "", "", 0, "", "", ""

    text = "\n".join(lines)
    if "Diagnósticos do Brasil" in text or "Drª. Christiany" in text:
        return analyze_pdf_biocell(text, references_path)

    name, gender, age, cpf, phone, doctor = extract_patient_info(lines)
    results = scan_results(lines, references, gender)

    diagnosis, prescriptions = build_diagnosis_and_prescriptions(results)
    return diagnosis, prescriptions, name, gender, age, cpf, phone, doctor


def analyze_pdf_biocell(text, references_path="json/references.json"):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    name = re.sub(r'\bCAD\d*\b$', '', lines[0], flags=re.IGNORECASE).strip().title() if lines else "Unknown"

    cpf_match = re.search(r'C\.?P\.?F\.?\s+(\d{3}\.\d{3}\.\d{3}-\d{2})', text)
    cpf = cpf_match.group(1) if cpf_match else ""

    birth_date_match = re.search(r'D\.?N\.?\s+(\d{2}/\d{2}/\d{4})', text)
    birth_date = birth_date_match.group(1) if birth_date_match else ""
    try:
        birth_date_dt = datetime.strptime(birth_date, "%d/%m/%Y")
        today = datetime.today()
        age = today.year - birth_date_dt.year - ((today.month, today.day) < (birth_date_dt.month, birth_date_dt.day))
    except:
        age = 0

    doctor_match = re.search(r'Dr[ªa\.]*\s+([A-ZÁÉÍÓÚÇ][^\n]+?)(?:CRF|CPF)', text, re.IGNORECASE)
    doctor = doctor_match.group(1).strip() if doctor_match else ""

    references = read_references(references_path)
    results = scan_results(lines, references, "")

    diagnosis, prescriptions = build_diagnosis_and_prescriptions(results)
    return diagnosis, prescriptions, name, "", age, cpf, "", doctor


def build_diagnosis_and_prescriptions(results):
    diagnosis_text = ""
    prescriptions = []
    for test, info in results.items():
        value, ideal, meds = info["value"], info["ideal"], info["medications"]
        if value is None or ideal is None:
            continue
        min_val, max_val = parse_min_max(str(ideal))
        if min_val is None or max_val is None:
            continue
        if value < min_val:
            diagnosis_text += f"{test}: value {value} BELOW ideal ({ideal}).\n"
            prescriptions.extend([{"test": test, **med} for med in meds])
        elif value > max_val:
            diagnosis_text += f"{test}: value {value} ABOVE ideal ({ideal}).\n"
            prescriptions.extend([{"test": test, **med} for med in meds])
        else:
            diagnosis_text += f"{test}: value {value} within ideal range ({ideal}).\n"

    seen = set()
    prescription_lines = []
    for med in prescriptions:
        key = med["nome"]
        if key not in seen:
            seen.add(key)
            prescription_lines.append(
                f"- {med['nome']}\nPreparation: {med['preparo']}\nApplication: {med['aplicacao']}\n"
            )

    return diagnosis_text.strip(), "\n".join(prescription_lines).strip()

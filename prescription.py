import re
import json
from PyPDF2 import PdfReader
from datetime import datetime

def read_pdf(file_path):
    try:
        reader = PdfReader(file_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""

        lines = text.splitlines()
        lines = [line.strip() for line in lines if line.strip()]
        if not lines:
            print(f"[read_pdf] Aviso: PDF lido, mas nenhum texto extraído.")
            return []

        return lines

    except Exception as e:
        print(f"Erro lendo o arquivo: {e}")
        return []


def extract_patient_info(lines):
    name = ""
    gender = ""
    birth_date = ""
    age = 0
    cpf = ""
    phone = ""
    doctor = ""

    for line in lines:
        line = line.strip()

        if line.startswith("Paciente "):
            name = line.replace("Paciente ", "").strip()

        if line.startswith("Médico"):
            doctor_clean = re.split(r"\s+RG|\s+Prontuário", line.replace("Médico", "").strip(), maxsplit=1)[0].strip()
            doctor = doctor_clean

        cpf_match = re.search(r'CPF\s+(\d{3}\.\d{3}\.\d{3}-\d{2})', line)
        if cpf_match:
            cpf = cpf_match.group(1)

        elif "Sexo" in line and "Dt nasc." in line:
            match = re.search(r"Sexo\s+([MF])\s+Dt nasc\. (\d{2}/\d{2}/\d{4})", line)
            if match:
                gender = match.group(1)
                birth_date = match.group(2)
                from datetime import datetime
                try:
                    birth_date_dt = datetime.strptime(birth_date, "%d/%m/%Y")
                    today = datetime.today()
                    age = today.year - birth_date_dt.year - ((today.month, today.day) < (birth_date_dt.month, birth_date_dt.day))
                except:
                    age = 0

    return name, gender, age, cpf, phone, doctor


def read_references(references_path):
    try:
        with open(references_path, "r", encoding="utf-8") as f:
            references = json.load(f)
            return references
    except FileNotFoundError:
        print(f"[read_references] Arquivo não encontrado: {references_path}")
    except json.JSONDecodeError as e:
        print(f"[read_references] JSON inválido em '{references_path}': {e}")
    return None


def parse_min_max(ideal_text: str):
    try:
        ideal_text = ideal_text.strip()
        if '\n' in ideal_text:
            ideal_text = ideal_text.split('\n')[0].strip()

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


def scan_results(lines: list[str], references: dict, gender) -> dict:
    results = {}
    number_pattern = re.compile(r"([0-9]+(?:[.,][0-9]+)?)")

    for test_name, test_info in references.items():
        found = False
        synonyms = [s.lower() for s in test_info.get("synonyms", [])] + [test_name.lower()]

        for line in lines:
            lower_line = line.lower()
            if any(term in lower_line for term in synonyms):
                found = True
                match = number_pattern.search(line)
                extracted_value = float(match.group(1).replace(",", ".")) if match else None

                ideal_data = test_info.get("ideal")
                ideal_text = None
                if isinstance(ideal_data, dict):
                    ideal_text = ideal_data.get(gender, next(iter(ideal_data.values())))
                elif isinstance(ideal_data, list):
                    for item in ideal_data:
                        min_val, max_val = parse_min_max(str(item))
                        if min_val is not None and max_val is not None:
                            ideal_text = item
                            break
                else:
                    ideal_text = ideal_data

                min_val, max_val = parse_min_max(str(ideal_text))
                medications = []

                if extracted_value is not None and min_val is not None:
                    if extracted_value < min_val:
                        medications = test_info.get("medications", {}).get("low", [])
                    elif max_val is not None and extracted_value > max_val:
                        medications = test_info.get("medications", {}).get("high", [])

                results[test_name] = {
                    "extracted_value": extracted_value,
                    "line": line.strip(),
                    "ideal": ideal_text,
                    "medications": medications
                }
                break

        if not found:
            results[test_name] = {
                "extracted_value": None,
                "line": None,
                "ideal": None,
                "medications": []
            }

    return results

def analyze_pdf(file_path, references_path="json/references.json"):
    lines = read_pdf(file_path)
    references = read_references(references_path)

    if lines is None or references is None:
        return "Erro ao ler o PDF ou as referências.", "", "", "", 0, "", "", ""

    # Concatena o texto em uma string só para análise por padrão
    texto = "\n".join(lines)

    if "Diagnósticos do Brasil" in texto or "Drª. Christiany" in texto:
        return analyze_pdf_biocell(texto)

    name, gender, age, cpf, phone, doctor = extract_patient_info(lines)
    results = scan_results(lines, references, gender)

    diagnostic_text = ""
    prescriptions_structured = []

    for test, info in results.items():
        extracted = info["extracted_value"]
        ideal_text = info["ideal"]
        meds = info["medications"]

        if extracted is None or ideal_text is None:
            continue

        min_val, max_val = parse_min_max(str(ideal_text))
        if min_val is None or max_val is None:
            continue

        if extracted < min_val:
            diagnostic_text += f"{test}: valor extraído {extracted} está ABAIXO do valor ideal ({ideal_text}).\n"
            prescriptions_structured.extend([{"exame": test, **med} for med in meds])
        elif extracted > max_val:
            diagnostic_text += f"{test}: valor extraído {extracted} está ACIMA do valor ideal ({ideal_text}).\n"
            prescriptions_structured.extend([{"exame": test, **med} for med in meds])
        else:
            diagnostic_text += f"{test}: valor extraído {extracted} está dentro do valor ideal ({ideal_text}).\n"

    # Agrupar prescrições por medicamento, evitando repetições
    seen = set()
    prescription_lines = []
    for item in prescriptions_structured:
        key = item["nome"]
        if key not in seen:
            seen.add(key)
            prescription_lines.append(
                f"- {item['nome']}\nPreparo: {item['preparo']}\nAplicação: {item['aplicacao']}\n"
            )

    prescription_text = "\n".join(prescription_lines)

    return diagnostic_text, prescription_text, name, gender, age, cpf, phone, doctor

import re
from datetime import datetime
import json

def analyze_pdf_biocell(texto: str, references_path="json/references.json"):
    # Nome
    linhas = texto.splitlines()
    linhas_limpa = [l.strip() for l in linhas if l.strip()]
    nome_raw = linhas_limpa[0] if linhas_limpa else "Desconhecido"

    # Remove "CAD" ou "CAD7" do final, se existir
    nome = re.sub(r'\bCAD\d*\b$', '', nome_raw, flags=re.IGNORECASE).strip().title()

    # CPF
    cpf_match = re.search(r'C\.?P\.?F\.?\s+(\d{3}\.\d{3}\.\d{3}-\d{2})', texto)
    cpf = cpf_match.group(1) if cpf_match else ""

    # Data de nascimento e idade
    dn_match = re.search(r'D\.?N\.?\s+(\d{2}/\d{2}/\d{4})', texto)
    data_nasc = dn_match.group(1) if dn_match else ""
    try:
        birth_date_dt = datetime.strptime(data_nasc, "%d/%m/%Y")
        today = datetime.today()
        age = today.year - birth_date_dt.year - ((today.month, today.day) < (birth_date_dt.month, birth_date_dt.day))
    except:
        age = 0

    # Médico responsável
    medico_match = re.search(r'Dr[ªa\.]*\s+([A-ZÁÉÍÓÚÇ][^\n]+?)(?:CRF|CPF)', texto, re.IGNORECASE)
    doctor_name = medico_match.group(1).strip() if medico_match else ""

    # Gênero deduzido pelo nome
    #gender = "Feminino" if nome.lower().split()[0].endswith("a") else "Masculino"
    gender = ""

    # Leitura das referências
    try:
        with open(references_path, "r", encoding="utf-8") as f:
            references = json.load(f)
    except:
        return "Erro ao ler referências", "", nome, gender, age, cpf, "", doctor_name

    # Processamento de linhas
    lines = texto.splitlines()
    lines = [line.strip() for line in lines if line.strip()]
    results = scan_results(lines, references, gender)

    diagnostic_text = ""
    prescriptions_structured = []

    for test, info in results.items():
        extracted = info["extracted_value"]
        ideal_text = info["ideal"]
        meds = info["medications"]

        if extracted is None or ideal_text is None:
            continue

        min_val, max_val = parse_min_max(str(ideal_text))
        if min_val is None or max_val is None:
            continue

        if extracted < min_val:
            diagnostic_text += f"{test}: valor extraído {extracted} está ABAIXO do valor ideal ({ideal_text}).\n"
            prescriptions_structured.extend([{"exame": test, **med} for med in meds])
        elif extracted > max_val:
            diagnostic_text += f"{test}: valor extraído {extracted} está ACIMA do valor ideal ({ideal_text}).\n"
            prescriptions_structured.extend([{"exame": test, **med} for med in meds])
        else:
            diagnostic_text += f"{test}: valor extraído {extracted} está dentro do valor ideal ({ideal_text}).\n"

    # Agrupar prescrições por medicamento, evitando repetições
    seen = set()
    prescription_lines = []
    for item in prescriptions_structured:
        key = item["nome"]
        if key not in seen:
            seen.add(key)
            prescription_lines.append(
                f"- {item['nome']}\nPreparo: {item['preparo']}\nAplicação: {item['aplicacao']}\n"
            )

    prescription_text = "\n".join(prescription_lines)

    return diagnostic_text.strip(), prescription_text.strip(), nome, gender, age, cpf, "", doctor_name

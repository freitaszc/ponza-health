import os
import re
import json
import requests
import fitz
import string
from datetime import datetime
from typing import Optional, List
from urllib.parse import urljoin
from flask import current_app, url_for
from itsdangerous import URLSafeSerializer
from difflib import get_close_matches

# Palavras/segmentos que comumente aparecem em cabeçalhos/rodapés e não são nomes
_NAME_STOPWORDS = {
    "responsavel", "responsável", "formula", "fórmula", "utilizada", "utilizado",
    "conferido", "liberado", "eletronicamente", "sob", "numero", "número", "nº",
    "laudo", "relatorio", "relatório", "exame", "paciente", "nome", "assinatura",
    "assinado", "dr", "dra", "crm", "crf", "cpf", "telefone", "contato"
}
_NAME_STOPWORDS.update({"data", "impressao", "impressão", "impressão"})

# artefatos comuns que aparecem concatenados ao nome
_NAME_ARTIFACTS = {"dn", "d.n.", "cad", "cad."}


def _is_plausible_name(name: str) -> bool:
    """Valida se a string parece um nome de pessoa em português.

    Regras heurísticas:
    - Deve ter entre 2 e 5 palavras úteis (descarta cabeçalhos longos)
    - Não deve conter dígitos nem muitos sinais de pontuação
    - Não deve conter stopwords comuns de rodapé/cabeçalho
    - Cada palavra deve ter ao menos 2 letras (exceto preposições aceitáveis)
    """
    if not name:
        return False
    s = name.strip()
    # comprimento razoável
    if len(s) < 3 or len(s) > 80:
        return False
    # não deve ter dígitos
    if re.search(r"\d", s):
        return False
    # rejeita presença de pontuação (permite hífen)
    punct = set(string.punctuation) - {"-"}
    if any(ch in punct for ch in s):
        return False
    parts = [p for p in re.split(r"\s+", s) if p]
    tokens_lower = [p.lower() for p in parts]
    # word count heuristics
    useful = [p for p in parts if len(p) > 1]
    if len(useful) < 2 or len(useful) > 6:
        return False
    # stopwords como palavras inteiras
    for bad in _NAME_STOPWORDS:
        if bad in tokens_lower:
            return False
    for art in _NAME_ARTIFACTS:
        if art in tokens_lower:
            return False
    # each meaningful part should look like a name token
    for p in useful:
        if re.search(r"[^A-Za-zÀ-ÿ\-óúãõâêîôçáéíúàèìòùÁÉÍÓÚÂÊÔÃÕÇ]", p):
            return False
        # tokens muito longos indicam concatenação OCR errada
        if len(p) < 2 or len(p) > 24:
            return False
    # exige pelo menos duas palavras com 3+ letras para evitar hashes tipo 'Ed Df Ac'
    if sum(1 for p in useful if len(p) >= 3) < 2:
        return False
    if not re.search(r"[aeiouáéíóúâêôãõà]", s.lower()):
        return False
    # tokens com tamanho médio muito alto também são suspeitos (um pouco mais permissivo)
    avg_len = sum(len(x) for x in useful) / max(1, len(useful))
    if avg_len > 14:
        return False
    return True

# ======================================================
# =============== VARIÁVEIS GLOBAIS ====================
# ======================================================

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"

WHATSAPP_API_URL = "https://graph.facebook.com/v18.0"
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
ADMIN_WHATSAPP = os.getenv("ADMIN_WHATSAPP", "").strip()

# ======================================================
# =============== PDF PARSING ===========================
# ======================================================

def _collapse_spaced_capitals(s: str) -> str:
    def repl(match: re.Match) -> str:
        group = match.group(0)
        return group.replace(" ", "")

    # Sequências de letras únicas em maiúsculas separadas por espaços (2+ ocorrências)
    return re.sub(r"\b(?:[A-ZÀ-ÿ]\s){2,}[A-ZÀ-ÿ]\b", repl, s)


def _split_fused_name(token: str) -> Optional[str]:
    if not token:
        return None
    s = re.sub(r"[^A-Za-zÀ-ÿ]", "", token).lower()
    if len(s) < 15:
        return None
    surnames = [
        "silva","santos","souza","oliveira","vieira","lima","louzada","almeida",
        "costa","pereira","cardoso","rodrigues","martins","barbosa","ferreira","carvalho",
        "araujo","barros","batista","dias","rezende","pires","teixeira","machado",
    ]
    # marca posições onde sobrenomes ocorrem
    cuts = []
    for sn in surnames:
        for m in re.finditer(sn, s):
            cuts.append((m.start(), m.end()))
    if not cuts:
        return None
    cuts.sort()
    words = []
    cursor = 0
    for a,b in cuts:
        if a > cursor:
            words.append(s[cursor:a])
        words.append(s[a:b])
        cursor = b
    if cursor < len(s):
        words.append(s[cursor:])
    # filtra palavras muito curtas/ruins
    words = [w for w in words if len(w) >= 2]
    if len(words) < 2:
        return None
    # capitaliza e remove duplicidades vizinhas
    final = []
    for w in words:
        t = w.capitalize()
        if not final or final[-1] != t:
            final.append(t)
    candidate = " ".join(final)
    return candidate if _is_plausible_name(candidate) else None


def _normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip())


def _sanitize_name_fragment(text: str) -> str:
    text = re.sub(r"[^A-Za-zÀ-ÿ\s-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _find_patient_name_from_lines(lines: List[str]) -> str:
    if not lines:
        return ""

    key_patterns = ("cad", "d.n", "data de nasc", "data de nascimento", "nasc", " dn")
    for idx, line in enumerate(lines):
        lower = line.lower()
        if any(key in lower for key in key_patterns):
            if idx > 0:
                cand = _sanitize_name_fragment(lines[idx - 1])
                if _is_plausible_name(cand):
                    return cand.title()
            prefix = re.split(r"(?i)(cad|d\.n\.|data de nascimento|nasc)", line)[0]
            cand = _sanitize_name_fragment(prefix)
            if _is_plausible_name(cand):
                return cand.title()

    best = ""
    for line in lines[:8]:
        cand = _sanitize_name_fragment(line)
        if _is_plausible_name(cand) and len(cand) > len(best):
            best = cand
    if best:
        return best.title()

    for idx, line in enumerate(lines):
        lower = line.lower()
        if "cad" in lower and idx > 0:
            fused = re.sub(r"[^A-Za-zÀ-ÿ]", "", lines[idx - 1])
            guess = _split_fused_name(fused)
            if guess:
                return guess

    phrase_pat = re.compile(r"([A-Za-zÀ-ÿ]{3,}(?:\s+[A-Za-zÀ-ÿ]{3,}){2,6})")
    best = ""
    for match in phrase_pat.finditer(" ".join(lines[:30])):
        cand = _sanitize_name_fragment(match.group(1))
        if _is_plausible_name(cand) and len(cand) > len(best):
            best = cand
    return best.title() if best else ""


def _find_doctor_from_lines(lines: List[str], patient_name: str) -> tuple[str, str, str]:
    best_name = ""
    best_score = -999
    best_cred_type = ""
    best_cred_digits = ""
    best_cred_region = ""
    patient_lower = (patient_name or "").lower()

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        normalized = re.sub(r"\s+", " ", line)
        if not re.search(r"(?i)(dr\.?|dra\.?|crm|crf|m[eé]dico)", normalized):
            continue
        cred_match = re.search(r"(?i)CR([MF])([-A-Z]*)\s*([0-9][0-9.\s]*)", normalized)
        cred_type = ""
        cred_digits = ""
        cred_region = ""
        if cred_match:
            cred_type = "CRM" if cred_match.group(1).lower() == "m" else "CRF"
            cred_region = (cred_match.group(2) or "").strip("- ")
            cred_digits = re.sub(r"\D", "", cred_match.group(3))
        before = normalized
        if cred_match:
            before = normalized[:cred_match.start()]
        before = before.rstrip("-: ")
        before = re.sub(r"^\([^)]{0,20}\)\s*", "", before)
        before = re.sub(r"(?i)^m[eé]dico(?:a)?\s*respons[áa]vel[:\-]?\s*", "", before)
        before = re.sub(r"(?i)^(?:dr\.?|dra\.?)\s+", "", before)
        candidate = _sanitize_name_fragment(before)
        if len(candidate.split()) < 2:
            continue
        if not _is_plausible_name(candidate):
            continue
        score = len(candidate.split())
        lower = normalized.lower()
        if "(r.t" in lower or "resp. técn" in lower:
            score += 1
        if cred_type == "CRM":
            score += 2
        elif cred_type == "CRF":
            score += 1
        if patient_lower and candidate.lower() == patient_lower:
            score -= 3
        if score > best_score:
            best_score = score
            best_name = candidate.title()
            best_cred_type = cred_type
            best_cred_digits = cred_digits
            best_cred_region = cred_region

    cred_label = best_cred_type
    if cred_label and best_cred_region:
        cred_label = f"{cred_label}-{best_cred_region.upper()}"
    return best_name, cred_label, best_cred_digits


def read_pdf(file_path):
    """Lê PDF com PyMuPDF (fitz), preservando layout e corrigindo fragmentação de caracteres sem remover espaços entre palavras."""
    try:
        text = ""
        with fitz.open(file_path) as doc:
            for page in doc:
                # Pega blocos de texto em ordem de leitura
                blocks = [b[4] for b in page.get_text("blocks")]
                page_text = "\n".join(blocks)

                # Remove múltiplos espaços e colapsa apenas letras isoladas com espaços
                page_text = re.sub(r"\s{2,}", " ", page_text)
                page_text = _collapse_spaced_capitals(page_text)
                text += page_text + "\n"

        # Divide em linhas e remove vazias
        return [line.strip() for line in text.splitlines() if line.strip()]
    except Exception as e:
        print(f"Error reading PDF with PyMuPDF: {e}")
        return []

# ======================================================
# =============== REFERÊNCIAS JSON ======================
# ======================================================

def read_references(references_path):
    try:
        with open(references_path, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception as e:
        print(f"Error reading references: {e}")
        return None

def parse_min_max(ideal_text):
    """Interpreta faixas numéricas do campo 'ideal'."""
    try:
        ideal_text = ideal_text.strip().split("\n")[0]
        if m := re.match(r"(≥|>=|>)\s*([0-9]+(?:[.,][0-9]+)?)", ideal_text):
            return float(m.group(2).replace(",", ".")), float("inf")
        if m := re.match(r"(≤|<=|<)\s*([0-9]+(?:[.,][0-9]+)?)", ideal_text):
            return float("-inf"), float(m.group(2).replace(",", "."))
        if m := re.search(r"([0-9]+(?:[.,][0-9]+)?)\s*[-–]\s*([0-9]+(?:[.,][0-9]+)?)", ideal_text):
            return float(m.group(1).replace(",", ".")), float(m.group(2).replace(",", "."))
        if m := re.search(r"([0-9]+(?:[.,][0-9]+)?)", ideal_text):
            v = float(m.group(1).replace(",", "."))
            return v, v
        return None, None
    except:
        return None, None


def _extract_json_object(text: str) -> Optional[str]:
    """Extrai o primeiro objeto JSON bem formado do texto usando contagem de chaves.
    Retorna a substring JSON ou None se não encontrar/match for inválido.
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i+1]
    return None

# ======================================================
# =============== EXTRAÇÃO DE PACIENTE =================
# ======================================================

def extract_patient_info(lines):
    """
    Extrai informações pessoais do paciente (nome, sexo, data de nascimento, idade, CPF, telefone e médico/CRM)
    de PDFs laboratoriais brasileiros. Prioriza heurísticas de linha e reforça limpezas específicas.
    """
    name = ""
    gender = ""
    birth_date = ""
    cpf = ""
    phone = ""
    doctor = ""
    age = 0

    normalized_lines = [_normalize_line(line) for line in lines]
    normalized_lines = [line for line in normalized_lines if line]
    joined_text = "\n".join(normalized_lines) if normalized_lines else "\n".join(lines)

    text_clean = re.sub(r"\s{2,}", " ", joined_text)
    try:
        text_clean = _collapse_spaced_capitals(text_clean)
    except Exception:
        pass

    name = _find_patient_name_from_lines(normalized_lines)
    if not name:
        if m := re.search(r"(?is)(?:^|\n)\s*(?:paciente|nome\s*do\s*paciente)\s*[:\-]?\s*([^\n]+)", joined_text):
            cand = _sanitize_name_fragment(m.group(1))
            if _is_plausible_name(cand):
                name = cand.title()
    if not name and lines:
        first_line = _sanitize_name_fragment(lines[0])
        if _is_plausible_name(first_line):
            name = first_line.title()

    patterns_dn = [
        r"(?i)(?:data\s*de\s*nascimento|nasc(?:imento)?|d\.?n\.?)[:\-]?\s*(\d{2}[/-]\d{2}[/-]\d{4})",
        r"D[.\s]*N[.:\s]*\s*(\d{2}[/-]\d{2}[/-]\d{4})"
    ]
    for pattern in patterns_dn:
        if m := re.search(pattern, text_clean):
            birth_date = m.group(1)
            break

    if m := re.search(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b", text_clean):
        cpf = m.group(0)

    if m := re.search(r"\(?\d{2}\)?\s?\d{4,5}[-\s]?\d{4}", text_clean):
        phone = m.group(0)

    if re.search(r"(?i)\bsexo[:\-]?\s*f", text_clean):
        gender = "F"
    elif re.search(r"(?i)\bsexo[:\-]?\s*m", text_clean):
        gender = "M"
    elif re.search(r"\bfeminino\b", text_clean, re.I):
        gender = "F"
    elif re.search(r"\bmasculino\b", text_clean, re.I):
        gender = "M"

    doctor_base, cred_label, cred_digits = _find_doctor_from_lines(normalized_lines, name)
    if not doctor_base:
        if m := re.search(r"(?is)([A-ZÀ-ÿ][A-Za-zÀ-ÿ\s\-]{3,}?)\s*[-–, ]*CRM\s*[:#-]?\s*(\d{4,7})", joined_text):
            doctor_base = _sanitize_name_fragment(m.group(1)).title()
            cred_digits = re.sub(r"\D", "", m.group(2))
            cred_label = "CRM"
        elif m := re.search(r"(?is)m[eé]dico(?:a)?\s*respons[áa]vel\s*[:\-]?\s*([^\n]+)", joined_text):
            doctor_base = _sanitize_name_fragment(m.group(1)).title()
        elif m := re.search(r"(?is)\bDr\.?\s+([^\n]+)", joined_text):
            doctor_base = _sanitize_name_fragment(m.group(1)).title()
        elif m := re.search(r"(?is)\bDra\.?\s+([^\n]+)", joined_text):
            doctor_base = _sanitize_name_fragment(m.group(1)).title()

    if doctor_base:
        doctor = doctor_base
        if cred_digits:
            label = cred_label or "CRM"
            doctor = f"{doctor} - {label} {cred_digits}"

    if birth_date:
        try:
            dob = datetime.strptime(birth_date, "%d/%m/%Y")
            today = datetime.today()
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        except Exception:
            age = 0
    elif m := re.search(r"(\d{1,3})\s*(?:anos|anos de idade)", text_clean, re.I):
        age = int(m.group(1))

    name = re.sub(r"\s+", " ", name)
    name = re.sub(r"(?i)\b(?:cad\s*dn|dn\s*cad)\b\.?$", "", name).strip()
    name = re.sub(r"(?i)\b(?:cad|dn|d\.n\.)\b\.?$", "", name).strip()
    name = re.sub(r"[^A-Za-zÀ-ÿ\s\-]", "", name).strip()

    doctor = re.sub(r"\s+", " ", doctor).strip()
    doctor = re.sub(r"[^A-Za-zÀ-ÿ0-9\s\-/]", " ", doctor)
    doctor = re.sub(r"\s+", " ", doctor).strip()
    doctor = re.sub(r"(?i)\bcrf\b\.?$", "", doctor).strip()
    doctor = re.sub(r"(?i)\bcrm\b(?!\s*\d)", "", doctor).strip()

    birth_date = birth_date.replace("-", "/").strip()

    if name and not _is_plausible_name(name):
        name = ""

    print(f"[INFO] Nome: {name}, Nasc: {birth_date}, Idade: {age}, CPF: {cpf}, Sexo: {gender}, Médico: {doctor}")
    return name, gender, age, cpf, phone, doctor, birth_date

# ======================================================
# =============== AI CORREÇÃO DE RESULTADOS =============
# ======================================================

def ai_validate_patient_info(lines, initial_data):
    """
    Usa IA para validar e corrigir informações extraídas de PDFs laboratoriais,
    garantindo nome completo e unificando CRM e nome do médico.
    """
    if not OPENAI_API_KEY:
        print("[AI validation skipped] OPENAI_API_KEY não configurada.")
        return initial_data

    try:
        joined_text = "\n".join(lines)
        # instruções reforçadas em português para reduzir respostas fora do formato
        prompt = f"""
Você é um assistente de leitura de laudos laboratoriais em português.
O texto abaixo foi extraído de um exame em português.
Seu objetivo é identificar e validar corretamente as informações do paciente e do médico.

Regras (responda em português):
- Corrija nomes abreviados como "S Dm" para o nome completo se aparecer em outra parte do texto.
- Combine o nome do médico com o CRM, mesmo que estejam separados (ex: "Célio Rodrigues Vieira" e "CRM 12345").
- Corrija erros comuns de OCR (ex: letras faltando, espaçamentos errados).
- Se alguma informação não estiver explícita, deixe o campo vazio.
- RETORNE APENAS E EXCLUSIVAMENTE UM OBJETO JSON VÁLIDO no formato abaixo, sem texto adicional.

Formato de saída:
{{
    "nome": "",
    "data_nascimento": "",
    "cpf": "",
    "sexo": "",
    "telefone": "",
    "medico": "",
    "crm": ""
}}

Texto do exame:
{joined_text[:6000]}

Informações extraídas inicialmente:
{json.dumps({
    "nome": initial_data[0],
    "sexo": initial_data[1],
    "idade": initial_data[2],
    "cpf": initial_data[3],
    "telefone": initial_data[4],
    "medico": initial_data[5],
    "data_nascimento": initial_data[6]
}, ensure_ascii=False, indent=2)}
"""

        response = requests.post(
            OPENAI_API_URL,
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0
            },
            timeout=45,
        )

        data = response.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        json_text = _extract_json_object(content)
        if json_text:
            ai_data = json.loads(json_text)

            # Une nome do médico e CRM, se separados
            medico_final = (ai_data.get("medico") or "").strip().title()
            crm_final = (ai_data.get("crm") or "").strip()
            if crm_final:
                # extrai apenas dígitos do CRM
                crm_digits = re.sub(r"\D", "", crm_final)
                if crm_digits and crm_digits not in medico_final:
                    medico_final = f"{medico_final} - CRM {crm_digits}" if medico_final else f"CRM {crm_digits}"
            # remove 'CRF' solto e 'CRM' sem dígitos
            medico_final = re.sub(r"(?i)\bcrf\b\.?$", "", medico_final).strip()
            medico_final = re.sub(r"(?i)\bcrm\b\.?$", "", medico_final).strip()

            nome_final = (ai_data.get("nome") or initial_data[0]).strip()
            # limpa artefatos finais no nome sugerido pela IA
            nome_final = re.sub(r"(?i)\b(?:cad\s*dn|dn\s*cad)\b\.?$", "", nome_final).strip()
            nome_final = re.sub(r"(?i)\b(?:cad|dn|d\.n\.)\b\.?$", "", nome_final).strip()
            sexo_final = (ai_data.get("sexo") or initial_data[1]).strip()
            cpf_final = (ai_data.get("cpf") or initial_data[3]).strip()
            telefone_final = (ai_data.get("telefone") or initial_data[4]).strip()
            dn_final = (ai_data.get("data_nascimento") or initial_data[6]).strip()

            # valida nome: se AI sugerir algo implausível, tenta fallback IA focado em nome
            if _is_plausible_name(nome_final):
                nome_used = nome_final.title()
            else:
                nome_used = initial_data[0].title() if _is_plausible_name(initial_data[0]) else ""
                if not nome_used:
                    # 2ª tentativa: prompt reduzido para extrair APENAS o nome do paciente
                    try:
                        prompt_nome = (
                            "Você receberá o texto de um laudo médico em português. "
                            "Identifique o nome COMPLETO do paciente, se existir, e retorne apenas JSON no formato {\"nome\": \"...\"}. "
                            "Ignore cabeçalhos e rodapés (ex.: 'Data de Impressão', 'Exame', 'Resultado', 'Médico', 'Paciente'). "
                            "Prefira a primeira ocorrência no topo do documento. Sem comentários, somente JSON.\n\nTEXTO:\n"
                            + joined_text[:6000]
                        )
                        resp2 = requests.post(
                            OPENAI_API_URL,
                            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
                            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt_nome}], "temperature": 0},
                            timeout=30,
                        )
                        data2 = resp2.json()
                        cont2 = data2.get("choices", [{}])[0].get("message", {}).get("content", "")
                        js2 = _extract_json_object(cont2)
                        if js2:
                            nome2 = (json.loads(js2).get("nome") or "").strip()
                            if _is_plausible_name(nome2):
                                nome_used = nome2.title()
                    except Exception:
                        pass

            # recomputa idade a partir da data de nascimento se possível
            age_final = initial_data[2]
            if dn_final:
                try:
                    dob = datetime.strptime(dn_final, "%d/%m/%Y")
                    today = datetime.today()
                    age_final = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
                except Exception:
                    # ignora se formato inválido
                    pass

            return (nome_used, sexo_final, age_final, cpf_final, telefone_final, medico_final, dn_final)
    except Exception as e:
        print(f"[AI validate error] {e}")

    return initial_data

# ======================================================
# =============== TESTE AUTOMÁTICO =====================
# ======================================================

if __name__ == "__main__":
    file_path = "/Users/gabriel/Downloads/Christiany.pdf"

    if not os.path.exists(file_path):
        print(f"[ERRO] O arquivo {file_path} não foi encontrado.")
    else:
        print(f"\n📄 Analisando: {file_path}")
        lines = read_pdf(file_path)
        if not lines:
            print("  ❌ Falha ao ler o PDF.")
        else:
            try:
                extracted = extract_patient_info(lines)
                validated = ai_validate_patient_info(lines, extracted)
                name, gender, age, cpf, phone, doctor, birth_date = validated
                print("  ✅ Extração final validada pela IA:")
                print(f"     Nome: {name}")
                print(f"     Data de Nascimento: {birth_date}")
                print(f"     Idade: {age}")
                print(f"     CPF: {cpf}")
                print(f"     Sexo: {gender}")
                print(f"     Telefone: {phone}")
                print(f"     Médico: {doctor}")
            except Exception as e:
                print(f"  ⚠️ Erro ao extrair informações: {e}")

def ai_refine_results(raw_text: str, initial_results: dict) -> dict:
    """Usa a IA para corrigir valores incorretos extraídos do PDF."""
    if not OPENAI_API_KEY:
        return initial_results
    clean_text = re.sub(r'\b\d{1,2}/\d{1,2}/\d{2,4}\b', '', raw_text)
    prompt = (
        "You are a clinical lab data parser. Given the extracted lab report and JSON results, "
        "fix incorrect numeric values. Ignore date-like patterns. Return valid JSON.\n\n"
        f"RAW TEXT:\n{clean_text[:6000]}\n\n"
        f"INITIAL JSON:\n{json.dumps(initial_results, ensure_ascii=False, indent=2)}"
    )
    try:
        response = requests.post(
            OPENAI_API_URL,
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}], "temperature": 0},
            timeout=25,
        )
        data = response.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        json_text = _extract_json_object(content)
        if not json_text:
            return initial_results
        corrected = json.loads(json_text)
        if not isinstance(corrected, dict):
            return initial_results

        # Função auxiliar para extrair número de uma string
        def _parse_number(v):
            if v is None:
                return None
            if isinstance(v, (int, float)):
                return float(v)
            s = str(v)
            m = re.search(r"([<>]?)\s*([0-9]+(?:[.,][0-9]+)?)", s)
            if m:
                num = m.group(2).replace(",", ".")
                try:
                    return float(num)
                except ValueError:
                    return None
            return None

        merged = dict(initial_results)
        for key, base in initial_results.items():
            corr = corrected.get(key)
            if not corr:
                continue
            # Cria nova cópia do dicionário base
            new = dict(base)
            # Tenta extrair value de várias formas
            if isinstance(corr, dict) and "value" in corr:
                new_val = _parse_number(corr.get("value"))
                if new_val is not None:
                    new["value"] = new_val
                # atualiza linha se fornecida
                if corr.get("line"):
                    new["line"] = corr.get("line")
                # merge medicamentos se fornecidos
                if corr.get("medications"):
                    new["medications"] = corr.get("medications")
            else:
                # corr pode ser valor simples
                new_val = _parse_number(corr)
                if new_val is not None:
                    new["value"] = new_val

            merged[key] = new

        return merged
    except Exception as e:
        print(f"[AI refine error] {e}")
    return initial_results

# ======================================================
# =============== AI ANÁLISE COMPLETA ==================
# ======================================================

def ai_full_analysis(file_path: str, references_path: str):
    """Análise completa via IA, comparando resultados com faixas ideais."""
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY não configurada.")

    # Lê texto do PDF
    lines = read_pdf(file_path)
    if not lines:
        raise ValueError("Falha ao ler o PDF.")
    raw_text = "\n".join(lines)
    raw_text = re.sub(r'\b\d{1,2}/\d{1,2}/\d{2,4}\b', '', raw_text)  # remove datas

    # Lê referências
    references = read_references(references_path)
    if not references:
        raise ValueError("Falha ao ler referências JSON.")

    prompt = f"""
You are a licensed medical assistant AI.
You will receive a laboratory report (Portuguese) and JSON with reference ranges.
Identify each test and numeric value.
Ignore any date-like values (e.g., 12/05/2024).
Compare results with reference ranges and produce a summary.

Output format (strict JSON):
{{
  "diagnosis": "Resumo médico em português",
  "prescription": "Lista de suplementos/recomendações"
}}

LAB REPORT:
{raw_text[:6000]}

REFERENCE VALUES JSON:
{json.dumps(references, ensure_ascii=False)[:6000]}
"""

    try:
        response = requests.post(
            OPENAI_API_URL,
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}], "temperature": 0},
            timeout=60,
        )
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        match = re.search(r"\{.*\}", content, re.S)
        if match:
            parsed = json.loads(match.group(0))
            return parsed.get("diagnosis", ""), parsed.get("prescription", "")
        raise ValueError("Falha ao interpretar resposta da IA.")
    except Exception as e:
        print(f"[AI full analysis error] {e}")
        raise

# ======================================================
# =============== ANÁLISE DE RESULTADOS ================
# ======================================================
def scan_results(lines, references, gender):
    results = {}
    normalized_lines = [line.lower() for line in lines]

    for test_name, info in references.items():
        synonyms = [s.lower() for s in info.get("synonyms", [])] + [test_name.lower()]
        best_match = None
        best_index = -1  # ← garante que seja sempre int

        for i, line in enumerate(normalized_lines):
            for synonym in synonyms:
                if synonym in line or get_close_matches(synonym, [line], cutoff=0.85):
                    best_match = line
                    best_index = i
                    break
            if best_match:
                break

        if best_index == -1:
            results[test_name] = {"value": None, "line": None, "ideal": None, "medications": []}
            continue

        combined_line = lines[best_index]
        if best_index + 1 < len(lines):
            combined_line += " " + lines[best_index + 1]

        # Ignora linhas que parecem datas
        if re.search(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", combined_line):
            results[test_name] = {"value": None, "line": combined_line, "ideal": None, "medications": []}
            continue

        m = re.search(r"([<>]?\s*\d+(?:[.,]\d{1,4})?)", combined_line)
        value = None
        if m:
            try:
                value = float(m.group(1).replace(",", ".").replace(">", "").replace("<", "").strip())
            except ValueError:
                value = None

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
            "line": combined_line.strip(),
            "ideal": ideal,
            "medications": meds,
        }

    return results

# ======================================================
# =============== DIAGNÓSTICO ==========================
# ======================================================
def build_diagnosis_and_prescriptions(results):
    """
    Monta texto de diagnóstico e lista de prescrições com base nos resultados.
    Garante que medicamentos não sejam perdidos e evita sobrescritas.
    """
    diagnosis_text = []
    prescriptions = []

    for test, info in results.items():
        value, ideal, meds = info["value"], info["ideal"], info["medications"]

        if value is None or not ideal:
            continue

        min_val, max_val = parse_min_max(str(ideal))
        if min_val is None or max_val is None:
            continue

        if value < min_val:
            diagnosis_text.append(f"{test}: valor {value} ABAIXO do ideal ({ideal}).")
            prescriptions.extend([{"test": test, **med} for med in meds])
        elif value > max_val:
            diagnosis_text.append(f"{test}: valor {value} ACIMA do ideal ({ideal}).")
            prescriptions.extend([{"test": test, **med} for med in meds])
        else:
            diagnosis_text.append(f"{test}: valor {value} dentro do ideal ({ideal}).")

    # Remove duplicadas e formata
    seen = set()
    prescription_lines = []
    for med in prescriptions:
        name = med.get("nome")
        if name and name not in seen:
            seen.add(name)
            prep = med.get("preparo", "—")
            appl = med.get("aplicacao", "—")
            prescription_lines.append(f"- {name}\nPreparo: {prep}\nAplicação: {appl}\n")

    return "\n".join(diagnosis_text).strip(), "\n".join(prescription_lines).strip()

# ======================================================
# =============== ANÁLISE GERAL DE PDF =================
# ======================================================

def analyze_pdf(source, references_path="json/references.json", manual=False):
    """
    Analisa o PDF e retorna diagnóstico, prescrição e dados do paciente.
    Inclui data de nascimento detectada pelo extrator.
    """
    references = read_references(references_path)

    if manual:
        lines = [l.strip() for l in source.splitlines() if l.strip()]
        gender = "F"
        results = scan_results(lines, references, gender)
        diagnosis, prescriptions = build_diagnosis_and_prescriptions(results)
        return diagnosis, prescriptions, "", gender, 0, "", "", "", ""

    lines = read_pdf(source)
    if not lines or not references:
        return "Erro ao extrair com IA", "", "", "", 0, "", "", "", ""

    raw_text = "\n".join(lines)

    try:
        name, gender, age, cpf, phone, doctor, birth_date = extract_patient_info(lines)
    except Exception as e:
        print(f"[analyze_pdf] Erro ao extrair dados pessoais: {e}")
        name, gender, age, cpf, phone, doctor, birth_date = "", "", 0, "", "", "", ""

    # Correção de resultados via IA
    results = scan_results(lines, references, gender)
    results = ai_refine_results(raw_text, results)

    # Diagnóstico e prescrição
    diagnosis, prescriptions = build_diagnosis_and_prescriptions(results)

    # Se prescrição vier vazia, tenta IA completa
    if not prescriptions.strip() and OPENAI_API_KEY:
        try:
            ai_dgn, ai_rx = ai_full_analysis(source, references_path)
            if ai_dgn: diagnosis += "\n\n" + ai_dgn
            if ai_rx: prescriptions = (prescriptions + "\n" + ai_rx).strip()
        except Exception as e:
            print(f"[AI full analysis fallback error] {e}")

    return diagnosis, prescriptions, name, gender, age, cpf, phone, doctor, birth_date

# ======================================================
# =============== WHATSAPP HELPERS =====================
# ======================================================

def _headers() -> dict:
    if not WHATSAPP_TOKEN:
        raise RuntimeError("WHATSAPP_TOKEN not configured")
    return {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}

def _endpoint() -> str:
    if not WHATSAPP_PHONE_NUMBER_ID:
        raise RuntimeError("WHATSAPP_PHONE_NUMBER_ID not configured")
    return f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/messages"

def _post_whatsapp(payload: dict) -> Optional[str]:
    try:
        resp = requests.post(_endpoint(), headers=_headers(), json=payload, timeout=30)
        if resp.status_code not in (200, 201):
            try:
                data = resp.json()
            except Exception:
                data = {"raw": resp.text}
            return f"WA API error {resp.status_code}: {data}"
        return None
    except Exception as e:
        return f"WA request failed: {e}"

def normalize_phone(msisdn: str) -> str:
    if not msisdn:
        return msisdn
    digits = re.sub(r"\D", "", msisdn)
    if digits.startswith("55") and len(digits) in (12, 13):
        return digits
    if len(digits) == 11 and not digits.startswith("55"):
        return f"55{digits}"
    return digits

# ======================================================
# =============== ENVIO DE RELATÓRIOS ==================
# ======================================================

def _build_public_pdf_link(patient_id: int) -> str:
    """Create a stable public link to the latest PDF for the given patient."""
    s = URLSafeSerializer(current_app.config["SECRET_KEY"])
    token = s.dumps(patient_id)
    relative_url = url_for("public_download", token=token, _external=False)
    base_url = (
        current_app.config.get("PUBLIC_BASE_URL")
        or current_app.config.get("APP_BASE_URL")
        or os.getenv("PUBLIC_APP_URL")
        or os.getenv("APP_BASE_URL")
    )
    if base_url:
        base = base_url.rstrip("/") + "/"
        rel = relative_url.lstrip("/")
        return urljoin(base, rel)
    return url_for("public_download", token=token, _external=True)


def send_pdf_whatsapp_template(template_name, doctor_name, patient_name, phone, patient_id, *, clinic_contact: Optional[str] = None):
    if not phone:
        return "Nenhum telefone informado."

    analyzed_link = _build_public_pdf_link(patient_id)
    contact_text = (clinic_contact or "").strip() or "-"

    parameters = [
        {"type": "text", "text": doctor_name or "-"},
        {"type": "text", "text": patient_name or "-"},
        {"type": "text", "text": analyzed_link},
        {"type": "text", "text": contact_text},
    ]

    payload = {
        "messaging_product": "whatsapp",
        "to": normalize_phone(phone),
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": "pt_BR"},
            "components": [{"type": "body", "parameters": parameters}],
        },
    }
    err = _post_whatsapp(payload)
    if err:
        print(f"[WA] Erro ao enviar relatório para o médico {doctor_name or ''}: {err}")
    return err

def send_pdf_whatsapp_patient(patient_name, patient_phone, patient_id, clinic_phone=None):
    if not patient_phone:
        return "Nenhum telefone informado."
    analyzed_link = _build_public_pdf_link(patient_id)
    payload = {
        "messaging_product": "whatsapp",
        "to": normalize_phone(patient_phone),
        "type": "template",
        "template": {
            "name": "relatorio_paciente_ponza",
            "language": {"code": "pt_BR"},
            "components": [{
                "type": "body",
                "parameters": [
                    {"type": "text", "text": patient_name or "-"},
                    {"type": "text", "text": analyzed_link},
                    {"type": "text", "text": clinic_phone or "-"}
                ],
            }],
        },
    }
    err = _post_whatsapp(payload)
    if err:
        print(f"[WA] Erro ao enviar relatório para o paciente {patient_name or ''}: {err}")
    return err

# ======================================================
# =============== ENVIO DE COTAÇÕES ====================
# ======================================================

def send_quote_whatsapp(supplier_name, phone, quote_title, quote_items, response_url):
    if not phone:
        return f"Fornecedor '{supplier_name}' sem telefone."
    to = normalize_phone(phone)
    items_text = " | ".join(f"• {it}" for it in (quote_items or [])[:10]).strip() or "-"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": "ponzahealth_cotacao",
            "language": {"code": "pt_BR"},
            "components": [{
                "type": "body",
                "parameters": [
                    {"type": "text", "text": supplier_name or "-"},
                    {"type": "text", "text": quote_title or "-"},
                    {"type": "text", "text": items_text},
                    {"type": "text", "text": response_url or "-"}
                ],
            }],
        },
    }
    err = _post_whatsapp(payload)
    if err:
        print(f"[WA] Erro ao enviar cotação para {supplier_name}: {err}")
    return err

# ======================================================
# =============== LEMBRETES ============================
# ======================================================

def send_reminder_doctor(clinic_phone, patient_name, clinic_name, date_str, time_start, time_end):
    if not clinic_phone:
        return "Nenhum telefone da clínica informado."
    payload = {
        "messaging_product": "whatsapp",
        "to": normalize_phone(clinic_phone),
        "type": "template",
        "template": {
            "name": "appointment_scheduling",
            "language": {"code": "pt_BR"},
            "components": [{
                "type": "body",
                "parameters": [
                    {"type": "text", "text": patient_name or "-"},
                    {"type": "text", "text": clinic_name or "-"},
                    {"type": "text", "text": date_str or "-"},
                    {"type": "text", "text": time_start or "-"},
                    {"type": "text", "text": time_end or "-"},
                ],
            }],
        },
    }
    return _post_whatsapp(payload)

def send_reminder_patient(patient_phone, patient_name, clinic_name, date_str, time_start, time_end):
    if not patient_phone:
        return "Nenhum telefone informado."
    payload = {
        "messaging_product": "whatsapp",
        "to": normalize_phone(patient_phone),
        "type": "template",
        "template": {
            "name": "appointment_scheduling",
            "language": {"code": "pt_BR"},
            "components": [{
                "type": "body",
                "parameters": [
                    {"type": "text", "text": patient_name or "-"},
                    {"type": "text", "text": clinic_name or "-"},
                    {"type": "text", "text": date_str or "-"},
                    {"type": "text", "text": time_start or "-"},
                    {"type": "text", "text": time_end or "-"},
                ],
            }],
        },
    }
    return _post_whatsapp(payload)

# ======================================================
# =============== TEXTO LIVRE ==========================
# ======================================================

def send_text(to_phone, text):
    to = normalize_phone(to_phone)
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"preview_url": True, "body": text},
    }
    return _post_whatsapp(payload)

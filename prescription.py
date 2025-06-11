from PyPDF2 import PdfReader
import json
import re

#reads the pdf

def read_pdf(file_path):
    try:
        reader = PdfReader(file_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""

        lines = text.splitlines()
        lines = [line.strip() for line in lines if line.strip()]
        if not lines:
            print(f"[read_pdf] Aviso: PDF lido, mas nenhum texto extraido.")
        return lines
    except Exception as e:
        print(f"Erro lendo o arquivo")
        return None

#reads json file with references 
def read_references(references_path):
    try:
        with open(references_path, "r", encoding = "utf-8") as f:
            references = json.load(f)
            return references
    except FileNotFoundError:
        print(f"[read_references] Arquivo não encontrado: {references_path}")
    except json.JSONDecodeError as e:
        print(f"[read_references] JSON inválido em '{references_path}': {e}")
    return None

#compare references with exam
def scan_results(lines: list[str], references: dict) -> dict:
    results = {}

    #capture the first integer or decimal number in a line
    number_pattern = re.compile(r"([0-9]+(?:[.,][0-9]+)?)")

    for test_name, test_info in references.items(): 
        found = False
        synonyms = [s.lower() for s in test_info.get("synonyms", [])] + [test_name.lower()]

        for line in lines:
            lower_line = line.lower()
            if any(term in lower_line for term in synonyms): #add synonyms later, if need 
                found = True

                match = number_pattern.search(line)
                if match:
                    raw_value = match.group(1).replace(",", ".")
                    try:
                        extracted_value = float(raw_value)
                    except ValueError:
                        extracted_value = None
                else:
                    extracted_value = None

                medication_suggestion = None
                if extracted_value is not None:
                    #se "ideal" for um dict (ex.: male/female), pega a primeira string
                    ideal_data = test_info.get("ideal")
                    if isinstance(ideal_data, dict):
                        first_key = next(iter(ideal_data))
                        ideal_text = ideal_data[first_key]
                    else:
                        ideal_text = ideal_data

                    min_val, max_val = parse_min_max(str(ideal_text))
                    if min_val is not None and max_val is not None:
                        if extracted_value < min_val:
                            medication_suggestion = test_info.get("medications", {}).get("low")
                        elif extracted_value > max_val:
                            medication_suggestion = test_info.get("medications", {}).get("high")

                results[test_name] = {
                    "extracted_value": extracted_value,
                    "line": line.strip(),
                    "ideal": test_info.get("ideal"),
                    "medication_suggestion": medication_suggestion
                }
                break

        if not found:
            results[test_name] = {
                "extracted_value": None,
                "line": None,
                "ideal": test_info.get("ideal"),
                "medication_suggestion": None
            }

    return results

def parse_min_max(ideal_text: str):
    #given a string like "75-90 mg/dL" or "14,0-16,0 g/dL",
    #return (min_value: float, max_value: float).
    #returns (None, None) if parsing fails.
    #look for two numbers (integers or decimals) separated by non-digits
    m = re.search(r"([0-9]+(?:[.,][0-9]+)?)[^\d]+([0-9]+(?:[.,][0-9]+)?)", ideal_text)
    if not m:
        return None, None
    try:
        min_val = float(m.group(1).replace(",", "."))
        max_val = float(m.group(2).replace(",", "."))
        return min_val, max_val
    except ValueError:
        return None, None


#main
if __name__ == "__main__":
    file_path = "report.pdf"
    references_path = "references.json"

    lines = read_pdf(file_path)
    if lines is None:
        print("Falha ao ler o PDF")
        exit(1)

    references = read_references(references_path)
    if references is None:
        print("Falha ao acessar o arquivo JSON")
        exit(1)

    results = scan_results(lines, references)
    
    print("\nResultados:\n")
for test, info in results.items():
    extracted = info["extracted_value"]
    ideal = info["ideal"]
    suggestion = info["medication_suggestion"]

    if extracted is None:
        continue

    if isinstance(ideal, dict):
        # pega a primeira faixa do dict (ex.: “male” ou “female”)
        first_key = next(iter(ideal))
        ideal_text = ideal[first_key]
    else:
        ideal_text = ideal

    min_val, max_val = parse_min_max(str(ideal_text))
    # se não conseguiu extrair intervalo numérico, pula
    if min_val is None or max_val is None:
        continue

    if extracted < min_val:
        print(f"  {test}: valor extraído {extracted} está ABAIXO do valor ideal ({min_val}–{max_val}).")
        if suggestion:
            print(f"    → Medicações sugeridas: {suggestion}\n")
    elif extracted > max_val:
        print(f"  {test}: valor extraído {extracted} está ACIMA do valor ideal ({min_val}–{max_val}).")
        if suggestion:
            print(f"   → Medicações sugeridas: {suggestion}\n")
import gradio as gr
from prescription import read_pdf, read_references, scan_results, parse_min_max

def analisar(pdf_file):
    lines = read_pdf(pdf_file.name)
    if lines is None:
        return "❌ Erro ao ler o PDF."

    references = read_references("references.json")
    if references is None:
        return "❌ Erro ao carregar o arquivo de referências (JSON)."

    results = scan_results(lines, references)
    
    output = ""
    for test, info in results.items():
        extracted = info["extracted_value"]
        ideal = info["ideal"]
        suggestion = info["medication_suggestion"]

        if extracted is None:
            continue

        if isinstance(ideal, dict):
            first_key = next(iter(ideal))
            ideal_text = ideal[first_key]
        else:
            ideal_text = ideal

        min_val, max_val = parse_min_max(str(ideal_text))
        if min_val is None or max_val is None:
            continue

        if extracted < min_val:
            output += f"❌ {test}: valor {extracted} está ABAIXO do ideal ({min_val}–{max_val}).\n"
            if suggestion:
                output += f"   → Medicação sugerida: {suggestion}\n\n"
        elif extracted > max_val:
            output += f"❌ {test}: valor {extracted} está ACIMA do ideal ({min_val}–{max_val}).\n"
            if suggestion:
                output += f"   → Medicação sugerida: {suggestion}\n\n"
        else:
            output += f"✅ {test}: valor {extracted} dentro do ideal ({min_val}–{max_val}).\n\n"

    return output if output.strip() else "Todos os exames estão dentro do intervalo ideal."

gr.Interface(
    fn=analisar,
    inputs=gr.File(label="Envie o PDF do laudo"),
    outputs=gr.Textbox(label="Resultado"),
    title="Analisador de Laudos Clínicos",
).launch(server_name="0.0.0.0", server_port=7860)

# Ponza Health

## Standalone Exam Analyzer

Uma aplicacao Flask minimalista para testar rapidamente a analise de laudos e a geracao de prescricoes por IA foi adicionada em `exam_analyzer/`.

### Como executar

```bash
cd Web/exam_analyzer
python3 -m venv .venv && source .venv/bin/activate  # opcional
pip install -r ../requirements.txt
export OPENAI_API_KEY="coloque_sua_chave"
python app.py
```

Depois acesse `http://localhost:5050` e envie um PDF de exame. O app le todo o texto do laudo, envia para a IA interpretar os valores (ela responde com JSON completo + prescricao) e exibe o resultado final em segundos.

### Debugger de linha de comando

Use `exam_analyzer/debugger.py` para investigar problemas no terminal (pipeline estruturado, montagem do payload e chamada da IA):

```bash
cd Web
python exam_analyzer/debugger.py caminho/para/laudo.pdf --require-ocr --run-ai
```

Ele mostra cada etapa, imprime rastros de excecao quando houver erros (ex.: PdfminerException) e reporta falhas da API (`401 Unauthorized`, etc.). O `--run-ai` e opcional caso queira evitar chamadas ao modelo.

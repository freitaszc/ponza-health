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

### Supabase e limites de conexões

O banco roda no Supabase e o PgBouncer deles tem um limite rígido de conexões simultâneas. Para evitar erros `MaxClientsInSessionMode`, configure as variáveis:

- `SUPABASE_DATABASE_URL`: URL completa do Postgres (use o endpoint `pooler` e mantenha `sslmode=require`).
- `SUPABASE_MAX_CLIENTS`: total de conexões que **esse** serviço pode consumir. Se o plano permitir 6 e outro serviço usa 2, defina `4`.
- `SUPABASE_RESERVED_CONNECTIONS` (opcional): subtrai conexões do valor acima para deixar vagas para scripts externos.
- `DB_FORCE_NULLPOOL=1`: força o SQLAlchemy a abrir/fechar cada conexão sob demanda (já entra automaticamente quando o limite é <= `WEB_CONCURRENCY`).
- `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`: usados quando o NullPool está desativado. Ajuste-os somente se você tiver um limite alto.
- `WEB_CONCURRENCY`: a Render permite definir o número de workers do Gunicorn por variável de ambiente. Defina `1` ou `2` se o Supabase tiver poucos slots.

O app agora controla um semáforo global antes de cada requisição que toca o banco, então requisições extras esperam em vez de disparar `OperationalError`. Ainda assim, se o Supabase estiver totalmente ocupado por outros clientes, será necessário liberar conexões ou aumentar o plano.

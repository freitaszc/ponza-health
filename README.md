# Ponza Health

### Technology to amplify clinic results

Platform that improves day-to-day clinic management and automation. Ponza Health bundles features that keep everything organized, fast, and easy to track.

### Custom dashboard

Charts and indicators that surface the most important metrics. You can follow appointments, patients, inventory, analyses, and more without digging around.

### AI exam analysis

Ponza Lab automates exam analysis. You can upload PDFs or enter data manually. The system interprets results, suggests medications, and next steps. Prescriptions are editable so the doctor can adjust to each case.

### Automated quotes

Send quotes to multiple suppliers via WhatsApp and receive responses as they fill out. Price and lead-time comparisons are ready with minimal effort.

### Patient catalog

Manage patients in a simple way. The system makes it easy to import records from other sources using files.

### Inventory control

Track product entry and exit, with recent movement history and a clear view of what needs attention.

### Agenda

Plan the day with clarity. Use filters, a waitlist, and quickly find upcoming appointments.

### How the app works (technical overview)

- React (Vite) frontend as an SPA with internal routing and fast screens.
- Flask backend exposing the API that powers dashboard, patients, quotes, inventory, and agenda.
- Postgres on Supabase, with extra care around PgBouncer connection limits.
- AI pipeline in `exam_analyzer` to process PDFs, apply OCR when needed, and call the model.
- Lightweight browser cache to speed up previously loaded screens.

# Ponza Health - Português

## Tecnologia para ampliar resultados de clínicas

Plataforma que melhora a gestão e a automação do dia a dia da clínica. A Ponza Health reúne features que deixam tudo mais organizado, rápido e fácil de acompanhar.

### Dashboard personalizado

Gráficos e indicadores que mostram as variáveis mais importantes. Você acompanha consultas, pacientes, estoque, análises e outros dados sem precisar ficar caçando informação.

### Análises de exames com IA

O Ponza Lab faz a análise automatizada de exames. Dá para enviar PDFs ou inserir os dados manualmente. O sistema interpreta resultados, sugere medicamentos e próximas ações. A prescrição é personalizável, então o médico ajusta o que fizer sentido para cada caso.

### Cotações automatizadas

Envie cotações para vários fornecedores via WhatsApp e receba respostas conforme forem preenchendo. O comparativo de preços e prazos fica pronto sem esforço.

### Catálogo de pacientes

Gerencie pacientes de forma simples. O sistema facilita a importação de cadastros de outro lugar por meio de arquivos.

### Controle de estoque

Tenha controle de entrada e saída dos produtos, com histórico completo das movimentações recentes e visão clara do que precisa de atenção.

### Agenda

Coordene o dia com clareza. Use filtros, lista de espera e encontre agendamentos dos próximos dias com poucos cliques.

## Como o app funciona (termos técnicos)

- Frontend em React (Vite) como SPA, com rotas internas e telas rápidas.
- Backend em Flask expondo a API que alimenta dashboard, pacientes, cotações, estoque e agenda.
- Banco Postgres no Supabase, com cuidado nos limites de conexão do PgBouncer.
- Pipeline de IA no `exam_analyzer` para processar PDFs, aplicar OCR quando necessário e chamar o modelo.
- Cache leve no navegador para acelerar telas que já foram carregadas.
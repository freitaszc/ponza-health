const sections = [
  {
    id: 'quem-somos',
    title: '1. Quem somos',
    content: (
      <p>
        Ponza Health é a controladora dos dados pessoais tratados no âmbito dos nossos produtos e serviços para
        clínicas e profissionais de saúde. Esta política se aplica aos nossos sites e às funcionalidades
        disponibilizadas aos clientes.
      </p>
    ),
  },
  {
    id: 'quais-dados',
    title: '2. Quais dados coletamos',
    content: (
      <>
        <h3>2.1. Dados de conta e autenticação</h3>
        <p>Nome, e-mail, telefone, cargo, empresa, credenciais de acesso e logs de autenticação.</p>
        <h3>2.2. Dados operacionais da plataforma</h3>
        <p>
          Informações inseridas por usuários autorizados (ex.: cadastros de pacientes, profissionais, agenda,
          cotações, estoque, arquivos PDF). Quando envolverem dados sensíveis (dados de saúde), o tratamento ocorre sob
          controles reforçados e conforme as instruções do cliente.
        </p>
        <h3>2.3. Dados técnicos</h3>
        <p>Endereço IP, tipo de navegador, dispositivo, páginas acessadas, identificadores de sessão e telemetria.</p>
        <h3>2.4. Suporte e comunicação</h3>
        <p>Conteúdo de tickets, mensagens de e-mail/WhatsApp, anexos e metadados necessários ao atendimento.</p>
      </>
    ),
  },
  {
    id: 'como-usamos',
    title: '3. Para que usamos (bases legais)',
    content: (
      <ul>
        <li>
          <strong>Execução de contrato:</strong> criar contas, prover funcionalidades, manter a plataforma.
        </li>
        <li>
          <strong>Legítimo interesse:</strong> melhorar recursos, prevenir fraudes, métricas agregadas de uso.
        </li>
        <li>
          <strong>Consentimento:</strong> comunicações de marketing e integrações opcionais (quando aplicável).
        </li>
        <li>
          <strong>Obrigação legal/regulatória:</strong> guarda de logs, respostas a autoridades, compliance.
        </li>
        <li>
          <strong>Proteção da vida/saúde:</strong> quando estritamente necessário em emergências.
        </li>
      </ul>
    ),
  },
  {
    id: 'compartilhamento',
    title: '4. Compartilhamento e operadores',
    content: (
      <p>
        Não vendemos seus dados. Compartilhamos apenas com operadores que nos auxiliam a prestar o serviço (ex.:
        hospedagem, envio de e-mails, suporte, análises agregadas), sempre sob contrato e com obrigações de segurança e
        confidencialidade. Integrações opcionais ativadas por você receberão dados somente na medida necessária para
        funcionar.
      </p>
    ),
  },
  {
    id: 'cookies',
    title: '5. Cookies e tecnologias similares',
    content: (
      <>
        <p>
          Usamos cookies estritamente necessários (login, segurança e preferência) e, se habilitados, cookies de
          desempenho para entender uso e melhorar a experiência.
        </p>
        <ul className="legal-badges">
          <li>
            <span className="legal-badge">Necessários</span> sessão, autenticação, prevenção de fraude.
          </li>
          <li>
            <span className="legal-badge">Desempenho</span> métricas agregadas e anônimas de uso (quando ativadas).
          </li>
        </ul>
      </>
    ),
  },
  {
    id: 'retencao',
    title: '6. Retenção e descarte',
    content: (
      <p>
        Mantemos dados pessoais apenas pelo tempo necessário para cumprir as finalidades desta política e obrigações
        legais/contratuais. Após o término, dados são eliminados ou anonimizados de forma segura.
      </p>
    ),
  },
  {
    id: 'seguranca',
    title: '7. Segurança da informação',
    content: (
      <>
        <ul>
          <li>Criptografia em trânsito (HTTPS/TLS) e em repouso quando aplicável.</li>
          <li>Controles de acesso por perfil e registro de atividades relevantes (logs).</li>
          <li>Backups e segregação de ambientes.</li>
          <li>Boas práticas de desenvolvimento seguro e correções contínuas.</li>
        </ul>
        <p className="legal-note">
          Nenhum sistema é 100% imune. Em caso de incidente com risco relevante, comunicaremos conforme a LGPD.
        </p>
      </>
    ),
  },
  {
    id: 'direitos',
    title: '8. Seus direitos (LGPD)',
    content: (
      <>
        <ul>
          <li>Confirmação da existência de tratamento e acesso aos dados.</li>
          <li>Correção de dados incompletos, inexatos ou desatualizados.</li>
          <li>Anonimização, bloqueio ou eliminação de dados desnecessários ou excessivos.</li>
          <li>Portabilidade a outro fornecedor, observados segredos comercial e industrial.</li>
          <li>Eliminação dos dados tratados com consentimento.</li>
          <li>Informação sobre compartilhamentos e possibilidade de não consentir quando aplicável.</li>
          <li>Revogação do consentimento e oposição a tratamentos irregulares.</li>
        </ul>
        <p>
          Para solicitar, use os canais no item <a href="#contato">Contato</a>. Responderemos dentro de prazos
          razoáveis.
        </p>
      </>
    ),
  },
  {
    id: 'transferencias',
    title: '9. Transferências internacionais',
    content: (
      <p>
        Alguns provedores podem estar fora do Brasil; adotamos mecanismos previstos na LGPD para essas transferências.
      </p>
    ),
  },
  {
    id: 'criancas',
    title: '10. Crianças e adolescentes',
    content: (
      <p>O uso por menores ocorre apenas via profissionais ou organizações autorizadas, com consentimento quando necessário.</p>
    ),
  },
  {
    id: 'contato',
    title: '11. Contato',
    content: (
      <>
        <p>Para exercer direitos, tirar dúvidas ou reportar incidentes, fale conosco:</p>
        <ul className="legal-contact">
          <li>
            Suporte:{' '}
            <a href="mailto:contato@ponzahealth.com" target="_blank" rel="noreferrer">
              contato@ponzahealth.com
            </a>{' '}
            — <a href="tel:+5533984613689">+55 33 98461-3689</a>
          </li>
        </ul>
      </>
    ),
  },
  {
    id: 'mudancas',
    title: '12. Mudanças nesta política',
    content: (
      <p>
        Podemos atualizar este documento para refletir ajustes legais, técnicos ou operacionais. A versão vigente é a
        publicada nesta página.
      </p>
    ),
  },
]

export default function PrivacyPolicy() {
  const dateLabel = new Date().toLocaleDateString('pt-BR')

  return (
    <div className="legal-page">
      <section className="page-hero compact">
        <div className="container page-hero-inner single">
          <div className="page-hero-copy">
            <span className="hero-kicker">Política de Privacidade</span>
            <h1 className="hero-title">Compromisso com dados sensíveis</h1>
            <p>
              Esta política explica como o Ponza Health coleta, usa, compartilha e protege dados pessoais no contexto
              dos nossos sites, produtos e serviços.
            </p>
            <p className="page-hero-meta">Vigência: {dateLabel}</p>
          </div>
        </div>
      </section>

      <section className="section legal-section">
        <div className="container legal-layout">
          <aside className="legal-toc">
            <h3>Conteúdo</h3>
            <ul>
              {sections.map((section) => (
                <li key={section.id}>
                  <a href={`#${section.id}`}>{section.title}</a>
                </li>
              ))}
            </ul>
          </aside>

          <div className="legal-content">
            {sections.map((section) => (
              <article key={section.id} id={section.id} className="legal-card">
                <h2>{section.title}</h2>
                {section.content}
              </article>
            ))}
          </div>
        </div>
      </section>
    </div>
  )
}

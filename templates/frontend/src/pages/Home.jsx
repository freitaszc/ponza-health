import { Link } from '../components/Router'

const heroBenefits = [
  'Teste gratuito de 14 dias com todas as ferramentas.',
  'Confirmações automáticas por e-mail e WhatsApp.',
  'Alertas de estoque mínimo e reposição inteligente.',
  'Leitura automática de PDFs e geração de condutas.',
]

const features = [
  {
    title: 'Cadastros inteligentes',
    description: 'Pacientes, médicos e empresas com vínculo entre dados e busca rápida.',
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden>
        <path d="M5.5 21a6.5 6.5 0 0 1 13 0" />
        <circle cx="12" cy="8" r="4" />
      </svg>
    ),
  },
  {
    title: 'Estoque organizado',
    description: 'Controle de itens, categorias e níveis mínimos com alertas de reposição.',
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden>
        <path d="M3 7l9-4 9 4v10l-9 4-9-4z" />
        <path d="M3 7l9 4 9-4" />
      </svg>
    ),
  },
  {
    title: 'Cotações automáticas',
    description: 'Envie solicitações a fornecedores e acompanhe respostas no mesmo painel.',
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden>
        <path d="M7 8h10M7 12h7" />
        <path d="M4 4h16v12H7l-3 3V4z" />
      </svg>
    ),
  },
  {
    title: 'Análise de PDFs',
    description: 'Leitura de exames, comparação de referências e geração de prescrições.',
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden>
        <path d="M14 2H6a2 2 0 0 0-2 2v16l4-4h8a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2z" />
        <path d="M21 21l-4-4" />
      </svg>
    ),
  },
]

const integrations = [
  {
    title: 'Google Calendar',
    description: 'Sincronize eventos e mantenha sua agenda atualizada entre plataformas.',
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden>
        <path d="M7 3v4M17 3v4" />
        <rect x="3" y="7" width="18" height="14" rx="2" />
        <path d="M3 11h18" />
      </svg>
    ),
  },
  {
    title: 'WhatsApp e e-mail',
    description: 'Envie cotações, PDFs e notificações para pacientes e fornecedores.',
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden>
        <path d="M21 15a4 4 0 0 1-4 4H9l-4 3v-3H5a4 4 0 0 1-4-4V6a4 4 0 0 1 4-4h12a4 4 0 0 1 4 4v9z" />
      </svg>
    ),
  },
  {
    title: 'PDFs e relatórios',
    description: 'Gere documentos automaticamente conforme regras e protocolos.',
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden>
        <path d="M14 2H6a2 2 0 0 0-2 2v16l4-4h8a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2z" />
        <path d="M21 21l-4-4" />
      </svg>
    ),
  },
]

export default function Home() {
  return (
    <>
      <section className="hero">
        <div className="container hero-grid">
          <div className="hero-content">
            <h1 className="hero-title fade-up delay-1">Transforme sua clínica em instantes</h1>
            <p className="mt-5 hero-subtitle fade-up delay-2">
              O <strong>Ponza Health</strong> simplifica todo o atendimento: agendamento, estoque, análise de exames e comunicação com
              pacientes em um fluxo único.
            </p>

            <ul className="plan-list hero-plan-list fade-up delay-4">
              {heroBenefits.map((item) => (
                <li key={item}>
                  <span className="check" aria-hidden="true" />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
          <aside className="hero-media fade-up delay-2" aria-label="Dashboard do sistema">
            <img
              src="/static/images/macponza.svg"
              alt="Dashboard médico do Ponza Health exibindo gestão de pacientes e indicadores"
              className="hero-image"
            />
          </aside>
        </div>
      </section>

      <section id="recursos" className="section features">
        <div className="container">
          <div className="section-head">
            <h2 className="section-title">Recursos principais</h2>
            <p className="section-subtitle">
              Os módulos que deixam o Ponza Health cuidar da sua operação, de ponta a ponta.
            </p>
          </div>

          <div className="features-layout">
            <aside className="features-media">
              <img
                src="/static/images/doctor.png"
                alt="Profissional de saúde em destaque"
                className="features-image is-flipped"
              />
            </aside>
            <div className="features-grid">
              {features.map((feature) => (
                <article className="feature-card fade-up" key={feature.title}>
                  <span className="feature-icon">
                    {feature.icon}
                  </span>
                  <div>
                    <h3>{feature.title}</h3>
                    <p>{feature.description}</p>
                  </div>
                </article>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section id="integracoes" className="section integrations">
        <div className="container">
          <div className="section-head">
            <h2 className="section-title">Integrações</h2>
            <p className="section-subtitle">
              Conecte o Ponza Health às ferramentas que sua equipe já usa diariamente.
            </p>
          </div>

          <div className="integrations-grid">
            {integrations.map((integration) => (
              <article className="integration-card fade-up" key={integration.title}>
                <span className="integration-icon">{integration.icon}</span>
                <h3>{integration.title}</h3>
                <p>{integration.description}</p>
              </article>
            ))}
          </div>

          <div className="cta-banner">
            <div>
              <h3>Quer ver o Ponza Health em ação?</h3>
              <p>Agende uma demonstração com nosso time e receba um diagnóstico gratuito da operação.</p>
            </div>
            <Link className="btn-primary" to="/ajuda">
              Falar com especialista
            </Link>
          </div>
        </div>
      </section>

    </>
  )
}

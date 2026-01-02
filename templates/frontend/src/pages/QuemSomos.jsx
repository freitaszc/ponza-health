import { Link } from '../components/Router'

const aboutSections = [
  {
    id: 'identidade',
    title: '1. Identidade',
    content: (
      <>
        <p>
          A <strong>Ponza Health</strong> é uma plataforma de automação e gestão para clínicas e profissionais de saúde.
          Unimos prontuário eletrônico, agenda, financeiro, estoque, protocolos e análise de documentos em um ambiente
          simples e seguro.
        </p>
        <p className="note">Foco no essencial: menos tarefas manuais, mais tempo para o cuidado com o paciente.</p>
      </>
    ),
  },
  {
    id: 'proposito',
    title: '2. Propósito & Missão',
    content: (
      <>
        <p>
          <strong>Propósito:</strong> Simplificar a operação de clínicas para ampliar o acesso a um cuidado
          eficiente e humano.
        </p>
        <p>
          <strong>Missão:</strong> Entregar um software robusto e intuitivo que reduza custos operacionais,
          melhore a experiência do paciente e apoie decisões clínicas com dados.
        </p>
      </>
    ),
  },
  {
    id: 'valores',
    title: '3. Valores',
    content: (
      <ul>
        <li>
          <strong>Ética e privacidade:</strong> dados de saúde exigem padrões elevados de proteção.
        </li>
        <li>
          <strong>Clareza e simplicidade:</strong> design limpo, fluxos objetivos.
        </li>
        <li>
          <strong>Confiabilidade:</strong> disponibilidade, suporte próximo e melhorias contínuas.
        </li>
        <li>
          <strong>Resultados:</strong> automatizar o que não precisa de gente, para que a equipe foque no paciente.
        </li>
      </ul>
    ),
  },
  {
    id: 'historia',
    title: '4. Nossa história',
    content: (
      <p>
        Nascemos da experiência prática em consultórios que enfrentavam planilhas dispersas, retrabalho e perda de tempo
        com burocracias. Evoluímos para uma solução única, com módulos integrados e implantação ágil.
      </p>
    ),
  },
  {
    id: 'como-funciona',
    title: '5. O que fazemos',
    content: (
      <ul>
        <li>
          <strong>Prontuário & protocolos:</strong> registros estruturados, anexos e modelos personalizados.
        </li>
        <li>
          <strong>Agenda & teleconsulta:</strong> múltiplos profissionais, confirmações e atendimentos online.
        </li>
        <li>
          <strong>Financeiro:</strong> recebíveis, repasses, indicadores essenciais.
        </li>
        <li>
          <strong>Estoque & compras:</strong> entradas/saídas, lotes e rastreio de insumos.
        </li>
        <li>
          <strong>Documentos & assinaturas:</strong> geração, gestão e assinatura digital.
        </li>
        <li>
          <strong>Automação:</strong> tarefas recorrentes, lembretes e análises a partir de PDFs.
        </li>
      </ul>
    ),
  },
  {
    id: 'tecnologia',
    title: '6. Tecnologia & Integrações',
    content: (
      <p>
        Arquitetura moderna, criptografia em trânsito (HTTPS/TLS) e integrações selecionadas (ex.: calendário, e-mail).
        Mantemos o core enxuto para priorizar desempenho e segurança, com APIs para extensões controladas.
      </p>
    ),
  },
  {
    id: 'seguranca',
    title: '7. Segurança & LGPD',
    content: (
      <>
        <ul>
          <li>Criptografia em trânsito e controles de acesso por perfil.</li>
          <li>Logs relevantes, backups e segregação de ambientes.</li>
          <li>
            Processos alinhados à <a href="/privacy_policy">Política de Privacidade</a> e à LGPD.
          </li>
        </ul>
        <p className="note">Incidentes relevantes são comunicados pelos canais apropriados, conforme a legislação.</p>
      </>
    ),
  },
  {
    id: 'equipe',
    title: '8. Equipe & Liderança',
    content: (
      <p>
        Somos um time multidisciplinar de produto, engenharia e especialistas em saúde. Priorizamos ciclos curtos de
        entrega, escuta ativa dos clientes e evolução contínua.
      </p>
    ),
  },
  {
    id: 'clientes',
    title: '9. Clientes & Segmentos',
    content: (
      <p>
        Atendemos clínicas e profissionais de diferentes especialidades. Nosso objetivo é ser parceiro de longo prazo,
        com implantação simples e suporte direto.
      </p>
    ),
  },
  {
    id: 'impacto',
    title: '10. Impacto & Números',
    content: (
      <ul>
        <li>Redução de retrabalho administrativo.</li>
        <li>Mais aderência a processos e protocolos.</li>
        <li>Visão consolidada do negócio para decisões melhores.</li>
      </ul>
    ),
  },
  {
    id: 'carreiras',
    title: '11. Carreiras',
    content: (
      <p>
        Quer construir saúde digital com propósito? Envie seu currículo ou portfólio para{' '}
        <a href="mailto:ponzahealth@gmail.com">ponzahealth@gmail.com</a>.
      </p>
    ),
  },
  {
    id: 'contato',
    title: '12. Contato',
    content: (
      <ul>
        <li>
          E-mail: <a href="mailto:ponzahealth@gmail.com">ponzahealth@gmail.com</a>
        </li>
        <li>
          Telefone/WhatsApp: <a href="tel:+5533984613689">+55 33 98461-3689</a>
        </li>
      </ul>
    ),
  },
]

export default function QuemSomos() {
  const today = new Date()
  const formattedDate = `${String(today.getDate()).padStart(2, '0')}/${String(today.getMonth() + 1).padStart(
    2,
    '0',
  )}/${today.getFullYear()}`

  return (
    <>
      <section className="page-hero about-hero compact">
        <div className="container page-hero-inner single">
          <div className="page-hero-copy">
            <h1 className="hero-title">
              Tecnologia para simplificar e potencializar gestão de clínicas e a jornada do
              paciente.
            </h1>
            <p className="page-hero-meta">
              Atualizado em: <span>{formattedDate}</span>
            </p>
          </div>
        </div>
      </section>

      <section className="section about-section">
        <div className="container about-layout">
          <aside className="about-nav">
            <h3>Conteúdo</h3>
            <ul>
              {aboutSections.map((section) => (
                <li key={section.id}>
                  <a href={`#${section.id}`}>{section.title}</a>
                </li>
              ))}
            </ul>
            <div className="about-cta">
              <Link className="btn-primary" to="/ajuda">
                Falar com o time
              </Link>
            </div>
          </aside>

          <div className="about-content">
            {aboutSections.map((section) => (
              <article className="about-card" id={section.id} key={section.id}>
                <h3>{section.title}</h3>
                {section.content}
              </article>
            ))}
          </div>
        </div>
      </section>
    </>
  )
}

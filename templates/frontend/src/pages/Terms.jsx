const sections = [
  {
    id: 'aceite',
    title: '1. Aceite e Definições',
    content: (
      <>
        <p>
          Ao criar uma conta, acessar ou utilizar o Ponza Health você concorda com estes Termos de Uso e com a nossa{' '}
          <a href="/privacy_policy">Política de Privacidade</a>. Se não concordar, não utilize o serviço.
        </p>
        <p>
          <strong>Definições resumidas:</strong> Serviços = software, APIs, site e recursos associados; Cliente = pessoa
          física/jurídica titular da conta; Usuário = pessoa autorizada pelo Cliente; Dados = informações inseridas,
          geradas ou transmitidas via Serviços.
        </p>
      </>
    ),
  },
  {
    id: 'elegibilidade',
    title: '2. Elegibilidade e Cadastro',
    content: (
      <ul>
        <li>Você declara ter capacidade legal para contratar e que as informações de cadastro são verdadeiras.</li>
        <li>O Cliente é responsável pela gestão de acessos dos Usuários (criação, permissões e revogação).</li>
        <li>Você deve manter suas credenciais em sigilo e notificar-nos sobre usos não autorizados.</li>
      </ul>
    ),
  },
  {
    id: 'licenca',
    title: '3. Licença de Uso e Propriedade',
    content: (
      <ul>
        <li>Concedemos licença limitada, não exclusiva e intransferível para usar os Serviços pelo prazo contratado.</li>
        <li>Não vendemos o software; o direito de propriedade intelectual sobre o Ponza permanece conosco.</li>
        <li>É vedado: engenharia reversa, cópia, modificação, revenda, scraping automatizado e uso para concorrência.</li>
      </ul>
    ),
  },
  {
    id: 'uso-aceitavel',
    title: '4. Uso Aceitável',
    content: (
      <ul>
        <li>Proibido inserir conteúdo ilegal, difamatório, discriminatório ou que infrinja direitos de terceiros.</li>
        <li>Não contorne controles de segurança, não sobrecarregue a infraestrutura, não use o serviço para spam.</li>
        <li>O Cliente é responsável pelo uso dos Usuários sob sua conta e pela conformidade setorial aplicável.</li>
        <li>
          <span className="legal-badge">Aviso clínico</span> O Ponza não presta ato médico. Decisões clínicas cabem ao
          profissional responsável.
        </li>
      </ul>
    ),
  },
  {
    id: 'planos',
    title: '5. Planos, Cobrança e Cancelamento',
    content: (
      <ul>
        <li>Assinaturas mensais/anuais podem ser cobradas antecipadamente. Impostos podem ser adicionados.</li>
        <li>Podemos atualizar preços, com aviso prévio razoável. A continuidade implica aceite do novo valor.</li>
        <li>Cancelamento: a assinatura permanece ativa até o fim do ciclo vigente; salvo exigência legal, não há reembolso.</li>
        <li>Inadimplência pode resultar em suspensão e posterior rescisão, com encargos conforme lei.</li>
        <li>Ao terminar o período de teste, a cobrança inicia se não houver cancelamento.</li>
        <li>Exportação: fornecemos meios razoáveis para exportar dados, observadas limitações técnicas e legais.</li>
      </ul>
    ),
  },
  {
    id: 'mensageria',
    title: '6. Mensageria e Integrações',
    content: (
      <>
        <p>
          Ao ativar integrações (ex.: Google Calendar, e-mail/WhatsApp), o Cliente autoriza o envio de dados mínimos
          necessários para o funcionamento.
        </p>
        <ul>
          <li>Mensagens automáticas devem respeitar consentimento e regras anti-spam da plataforma.</li>
          <li>Serviços de terceiros possuem termos próprios; o Ponza não se responsabiliza por indisponibilidade.</li>
        </ul>
      </>
    ),
  },
  {
    id: 'dados',
    title: '7. Privacidade e Proteção de Dados (LGPD)',
    content: (
      <>
        <p>
          Tratamos dados conforme a <a href="/privacy_policy">Política de Privacidade</a> e a LGPD (Lei nº 13.709/2018).
          Para dados sensíveis de saúde, aplicamos controles reforçados e hipóteses legais cabíveis (art. 11), conforme
          configuração do Cliente.
        </p>
        <ul>
          <li>O Cliente é responsável por bases legais e pelo conteúdo inserido.</li>
          <li>Celebramos contratos com operadores (hospedagem, e-mail etc.) com obrigações de segurança.</li>
        </ul>
      </>
    ),
  },
  {
    id: 'suporte',
    title: '8. Disponibilidade, Suporte e Atualizações',
    content: (
      <ul>
        <li>Envidamos esforços razoáveis para manter o serviço disponível e seguro.</li>
        <li>Suporte é prestado pelos canais informados e dentro de prazos razoáveis.</li>
        <li>Podemos lançar recursos beta de forma experimental, sem garantias.</li>
        <li>Podemos alterar, suspender ou descontinuar funcionalidades, buscando minimizar impactos.</li>
      </ul>
    ),
  },
  {
    id: 'conteudo',
    title: '9. Conteúdos de Usuário',
    content: (
      <ul>
        <li>O Cliente mantém a titularidade sobre seus dados; concede licença para armazenar e processar conforme necessário.</li>
        <li>É vedado inserir material que viole direitos de terceiros (autorais, imagem, marcas).</li>
      </ul>
    ),
  },
  {
    id: 'responsabilidade',
    title: '10. Isenções e Limitação de Responsabilidade',
    content: (
      <ul>
        <li>Os Serviços são fornecidos “no estado em que se encontram” e “conforme disponibilidade”.</li>
        <li>Não garantimos ausência total de erros, interrupções ou perda de dados.</li>
        <li>
          Na máxima extensão permitida, não nos responsabilizamos por lucros cessantes, perda de receitas ou danos
          indiretos.
        </li>
        <li>Responsabilidade total agregada limitada ao montante pago nos 12 meses anteriores ao evento.</li>
      </ul>
    ),
  },
  {
    id: 'indenizacao',
    title: '11. Indenização',
    content: (
      <p>
        O Cliente concorda em indenizar o Ponza por reclamações de terceiros decorrentes do uso dos Serviços em desacordo
        com estes Termos, com a lei ou com direitos de terceiros.
      </p>
    ),
  },
  {
    id: 'suspensao',
    title: '12. Suspensão e Rescisão',
    content: (
      <ul>
        <li>Podemos suspender ou encerrar o acesso por violação destes Termos, risco de segurança, ordem legal ou inadimplência.</li>
        <li>O Cliente pode encerrar a conta a qualquer momento; após rescisão, dados podem ser retidos pelo prazo legal mínimo.</li>
      </ul>
    ),
  },
  {
    id: 'lei-foro',
    title: '13. Lei Aplicável e Foro',
    content: (
      <p>
        Estes Termos são regidos pelas leis do Brasil. Fica eleito o foro de Belo Horizonte/MG para dirimir
        controvérsias, salvo competência legal diversa.
      </p>
    ),
  },
  {
    id: 'alteracoes',
    title: '14. Alterações destes Termos',
    content: (
      <p>
        Podemos atualizar estes Termos para refletir mudanças legais ou operacionais. Alterações relevantes serão
        comunicadas pelos canais adequados.
      </p>
    ),
  },
  {
    id: 'contato',
    title: '15. Contato',
    content: (
      <ul className="legal-contact">
        <li>
          E-mail:{' '}
          <a href="mailto:contato@ponzahealth.com" target="_blank" rel="noreferrer">
            contato@ponzahealth.com
          </a>
        </li>
        <li>
          Telefone/WhatsApp: <a href="tel:+5533984613689">+55 33 98461-3689</a>
        </li>
      </ul>
    ),
  },
]

export default function Terms() {
  const dateLabel = new Date().toLocaleDateString('pt-BR')

  return (
    <div className="legal-page">
      <section className="page-hero compact">
        <div className="container page-hero-inner single">
          <div className="page-hero-copy">
            <span className="hero-kicker">Termos de Uso</span>
            <h1 className="hero-title">Contrato de licença e serviço</h1>
            <p>Regras que regem o acesso e o uso do Ponza Health — software, site e serviços relacionados.</p>
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

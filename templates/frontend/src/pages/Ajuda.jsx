import { useState } from 'react'

const helpTopics = [
  {
    title: 'Primeiros passos',
    description: 'Configuração inicial, importação de cadastros e checklist de implantação.',
  },
  {
    title: 'Agenda e atendimento',
    description: 'Confirmações automáticas, teleconsulta, check-in digital e filas inteligentes.',
  },
  {
    title: 'Laboratório',
    description: 'Solicitações, laudos e integração com o Ponza Lab em tempo real.',
  },
  {
    title: 'Financeiro',
    description: 'Cobranças, conciliação e relatórios para tomada de decisão.',
  },
]

const helpChannels = [
  {
    title: 'Chat com especialistas',
    description: 'Atendimento humano em horário estendido.',
  },
  {
    title: 'Base de conhecimento',
    description: 'Guias rápidos e boas práticas por módulo.',
  },
  {
    title: 'Comunidade',
    description: 'Troca de experiências entre clínicas e laboratórios.',
  },
]

const homeFaqs = [
  {
    question: 'Consigo importar meus dados atuais?',
    answer:
      'Sim. É possível importar cadastros e catálogos via planilhas ou integrações. Nosso time acompanha todo o processo.',
  },
  {
    question: 'É possível personalizar regras de análise?',
    answer: 'Sim. Ajuste parâmetros de referência e gatilhos para prescrições de acordo com seu protocolo.',
  },
  {
    question: 'O Ponza Health funciona no celular?',
    answer: 'Funciona. A interface é responsiva e acompanha o fluxo da equipe em qualquer dispositivo.',
  },
  {
    question: 'Quanto tempo leva para implementar?',
    answer: 'Em média, de 3 a 7 dias úteis com importação e treinamento.',
  },
  {
    question: 'Meus dados ficam seguros?',
    answer: 'Sim. Criptografia ponta a ponta e conformidade com LGPD em todas as camadas.',
  },
]

const helpFaqGroups = [
  {
    title: 'Cadastros',
    items: [
      {
        question: 'Como cadastrar um paciente com foto de perfil?',
        answer: (
          <>
            Vá em <strong>Pacientes → Cadastrar</strong>, preencha os dados e clique em{' '}
            <em>Alterar Foto de Perfil</em> para enviar a imagem. Ao salvar, a foto será associada ao registro.
          </>
        ),
      },
      {
        question: 'Posso editar ou excluir um cadastro depois?',
        answer: (
          <>
            Sim. Acesse o paciente, clique em <strong>Editar</strong> para alterar campos ou use as opções de exclusão
            conforme suas permissões.
          </>
        ),
      },
      {
        question: 'Como ver as análises do paciente?',
        answer: (
          <>
            Na área de <strong>Paciente</strong>, clique em <em>Opções</em>. Clique em <em>Ver diagnóstico</em> e você
            terá acesso completo a todos os diagnósticos feitos.
          </>
        ),
      },
    ],
  },
  {
    title: 'Agenda',
    items: [
      {
        question: 'Como marcar e confirmar consultas automaticamente?',
        answer: (
          <>
            Crie o evento na <strong>Agenda</strong> e ative lembretes automáticos (e-mail/WhatsApp). O paciente recebe
            confirmação e você acompanha o status.
          </>
        ),
      },
    ],
  },
  {
    title: 'Estoque',
    items: [
      {
        question: 'Como configurar alertas de estoque mínimo?',
        answer: (
          <>
            No módulo <strong>Dashboard</strong>, todos os produtos que estiverem com menos de 5 unidades estarão no
            gráfico &quot;Estoque baixo&quot;. Dessa forma você tem controle e sabe quando realizar as cotações e
            encomendas.
          </>
        ),
      },
      {
        question: 'O sistema controla entradas e saídas de produtos no estoque?',
        answer: (
          <>
            Sim. No módulo de <strong>Estoque</strong> você tem acesso a duas opções: uma de saída e outra de entrada.
            Assim você consegue atualizar seu estoque a qualquer momento, com facilidade e praticidade.
          </>
        ),
      },
    ],
  },
  {
    title: 'Cotações',
    items: [
      {
        question: 'Como enviar uma cotação a fornecedores?',
        answer: (
          <>
            Acesse <strong>Cotações</strong>, crie uma solicitação e selecione os fornecedores. Você pode disparar por
            e-mail/WhatsApp e acompanhar respostas no painel.
          </>
        ),
      },
      {
        question: 'Consigo comparar propostas e aprovar?',
        answer: (
          <>
            Sim. Visualize lado a lado por preço e prazo. Quando decidir, entre em contato com os fornecedores e faça
            seu pedido.
          </>
        ),
      },
    ],
  },
  {
    title: 'Geral',
    items: [
      {
        question: 'O Ponza Health está em conformidade com a LGPD?',
        answer: (
          <>
            Sim. Seguimos boas práticas de segurança e privacidade, com controles de acesso, registro de auditoria e
            políticas adequadas.
          </>
        ),
      },
      {
        question: 'Como falo com o suporte e peço treinamento?',
        answer: (
          <>
            Use o botão de WhatsApp, envie e-mail para{' '}
            <a href="mailto:contato@ponzahealth.com">contato@ponzahealth.com</a> ou agende um onboarding no primeiro mês
            sem custo.
          </>
        ),
      },
    ],
  },
]

const planFaqs = [
  {
    question: 'Qual a diferença entre o plano mensal e o anual?',
    answer:
      'O plano mensal custa R$ 79,90 e pode ser cancelado a qualquer momento. O plano anual é pago uma única vez por R$ 838,80, equivalente a R$ 69,90/mês — oferecendo economia e benefícios extras.',
  },
  {
    question: 'Posso mudar do plano mensal para o anual depois?',
    answer: 'Sim. Basta entrar em contato com o suporte que ajustaremos sua assinatura sem perda de dados.',
  },
  {
    question: 'O que acontece quando acabarem as 25 análises grátis?',
    answer: 'Você pode continuar normalmente e adquirir pacotes adicionais de análises conforme sua necessidade.',
  },
  {
    question: 'Posso cancelar quando quiser?',
    answer: 'Sim, sem burocracia. Seu acesso permanece até o fim do ciclo já pago.',
  },
]

const allFaqGroups = [
  {
    title: 'Perguntas iniciais',
    items: homeFaqs,
  },
  ...helpFaqGroups,
  {
    title: 'Planos',
    items: planFaqs,
  },
]

export default function Ajuda() {
  const [isTicketModalOpen, setIsTicketModalOpen] = useState(false)

  const handleOpenTicket = () => setIsTicketModalOpen(true)
  const handleCloseTicket = () => setIsTicketModalOpen(false)

  const handleTicketSubmit = (event) => {
    event.preventDefault()
    setIsTicketModalOpen(false)
  }
  return (
    <>
      <section className="page-hero help-hero compact">
        <div className="container page-hero-inner single">
          <div className="page-hero-copy">
            <h1 className="hero-title">Suporte humano e base completa de conhecimento</h1>
            <p>Encontre respostas rápidas ou fale direto com nosso time para acelerar a operação.</p>
          </div>
        </div>
      </section>

      <section className="section help-topics">
        <div className="container">
          <div className="section-head">
            <h2 className="section-title">Comece por aqui</h2>
            <p className="section-subtitle">Guias rápidos para as rotinas mais buscadas.</p>
          </div>
          <div className="help-grid">
            {helpTopics.map((topic) => (
              <article className="help-card" key={topic.title}>
                <h3>{topic.title}</h3>
                <p>{topic.description}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="section faq">
        <div className="container">
          <div className="section-head">
            <h2 className="section-title">Perguntas frequentes</h2>
          </div>
          <div className="faq-groups">
            {allFaqGroups.map((group) => (
              <div className="faq-group" key={group.title} id={group.title === 'Planos' ? 'planos' : undefined}>
                <h3 className="faq-group-title">{group.title}</h3>
                <div className="faq-grid">
                  {group.items.map((faq) => (
                    <details key={faq.question} className="faq-item">
                      <summary>{faq.question}</summary>
                      <p>{faq.answer}</p>
                    </details>
                  ))}
                </div>
              </div>
            ))}
          </div>
          <div className="help-actions help-actions--footer">
            <button className="btn-primary" type="button" onClick={handleOpenTicket}>
              Criar chamado
            </button>
            <a
              className="btn-outline btn-whatsapp"
              href="https://wa.me/5533984613689?text=Ol%C3%A1%2C%20preciso%20de%20ajuda%20com%20o%20Ponza%20Health"
              target="_blank"
              rel="noopener noreferrer"
            >
              Enviar mensagem no WhatsApp
            </a>
          </div>
        </div>
      </section>


      {isTicketModalOpen ? (
        <div
          className="support-modal"
          role="dialog"
          aria-modal="true"
          aria-labelledby="support-modal-title"
          onClick={(event) => {
            if (event.target === event.currentTarget) {
              handleCloseTicket()
            }
          }}
        >
          <div className="support-modal-card">
            <button className="support-modal-close" type="button" onClick={handleCloseTicket} aria-label="Fechar">
              x
            </button>
            <h3 id="support-modal-title">Abrir chamado</h3>
            <p className="support-modal-subtitle">
              Preencha os dados para que nosso time retorne o contato o quanto antes.
            </p>
            <form className="support-modal-form" onSubmit={handleTicketSubmit}>
              <label>
                Nome
                <input type="text" name="name" placeholder="Seu nome" required />
              </label>
              <label>
                E-mail
                <input type="email" name="email" placeholder="nome@clinica.com" required />
              </label>
              <label>
                Nome da clinica (opcional)
                <input type="text" name="clinic" placeholder="Nome da clinica" />
              </label>
              <label>
                Motivo do chamado
                <textarea name="reason" placeholder="Descreva como podemos ajudar" rows="4" required />
              </label>
              <div className="support-modal-actions">
                <button className="btn-primary" type="submit">
                  Enviar chamado
                </button>
                <button className="btn-ghost" type="button" onClick={handleCloseTicket}>
                  Cancelar
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </>
  )
}

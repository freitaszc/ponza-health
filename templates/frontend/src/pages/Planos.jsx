import { Link } from '../components/Router'

const pricingPlans = [
  {
    id: 'mensal',
    title: 'Plano Mensal',
    lead: 'Flexibilidade total para clínicas que desejam testar e crescer com liberdade.',
    price: { currency: 'R$', amount: '79,90', per: '/ mês' },
    features: [
      'Assinatura recorrente mensal',
      <>
        Período de teste gratuito de <strong>14 dias</strong>
      </>,
      <>
        <strong>25 análises gratuitas</strong> no Ponza Lab
      </>,
      <>
        <strong>Envio automático via WhatsApp</strong> dos resultados
      </>,
      <>
        <strong>Módulos completos:</strong> agenda, estoque, cotações e leitura de PDFs
      </>,
      'Cancelamento a qualquer momento',
    ],
  },
  {
    id: 'anual',
    title: 'Plano Anual',
    highlight: '12,5% OFF',
    lead: 'Economize R$120/ano com o plano para clínicas que buscam estabilidade.',
    price: { currency: 'R$', amount: '69,90', per: '/ mês' },
    features: [
      <>
        <strong>Pagamento único anual</strong> (R$ 838,80)
      </>,
      <>
        <strong>Economia de R$ 120/ano</strong> em relação ao plano mensal
      </>,
      <>
        <strong>25 análises gratuitas</strong> incluídas para iniciar
      </>,
      <>
        <strong>Bônus anual de 30 análises</strong> (total de 55 inclusas)
      </>,
      'Todos os módulos e atualizações incluídos',
      'Onboarding guiado e suporte premium com prioridade',
    ],
  },
]

export default function Planos() {
  return (
    <>
      <section className="page-hero compact">
        <div className="container page-hero-inner single">
          <div className="page-hero-copy">
            <h1 className="hero-title">Planos e preços</h1>
            <p className="page-hero-subtitle">
              Tudo que sua clínica precisa em um único sistema — simples, transparente e pronto para escalar.
            </p>
          </div>
        </div>
      </section>

      <section className="section pricing section--divider-top">
        <div className="container">
          <div className="section-head">
            <h2 className="section-title section-title--lift">Planos transparentes e escaláveis</h2>
            <p className="section-subtitle">
              Escolha o plano ideal e personalize conforme o tamanho da sua operação.
            </p>
          </div>

          <div className="pricing-grid">
            {pricingPlans.map((plan) => (
              <article key={plan.id} className={`pricing-card ${plan.highlight ? 'is-featured' : ''}`}>
                <div className="pricing-card-head">
                  <div className="pricing-title-row">
                    <h3>{plan.title}</h3>
                    {plan.highlight ? <span className="pricing-badge">{plan.highlight}</span> : null}
                  </div>
                  <p className="pricing-lead">{plan.lead}</p>
                </div>
                {plan.savings ? <div className="pricing-savings">{plan.savings}</div> : null}
                <div className="plan-price">
                  <span className="price-currency">{plan.price.currency}</span>
                  <strong>{plan.price.amount}</strong>
                  <span>{plan.price.per}</span>
                </div>
                <ul className="plan-list">
                  {plan.features.map((feature, index) => (
                    <li key={`${plan.id}-${index}`}>
                      <span className="check" />
                      <span>{feature}</span>
                    </li>
                  ))}
                </ul>
                <div className="plan-actions">
                  <Link className="btn-primary" to={`/cadastro?plan=${plan.id}`}>
                    Iniciar teste gratuito
                  </Link>
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="section plans-help">
        <div className="container">
          <div className="hero-actions hero-actions--center">
            <Link className="btn-primary" to="/ajuda#planos">
              Ver dúvidas sobre planos
            </Link>
          </div>
        </div>
      </section>
    </>
  )
}

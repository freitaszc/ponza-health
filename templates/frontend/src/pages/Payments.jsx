import { useMemo, useState } from 'react'

const backendBase = import.meta.env.VITE_BACKEND_URL || ''
const withBackend = (path) => (backendBase ? `${backendBase}${path}` : path)
const resolvePath = (href) => {
  if (!href) return ''
  if (/^https?:\/\//.test(href)) {
    try {
      return new URL(href).pathname
    } catch {
      return href
    }
  }
  return href
}

const navItems = [
  { label: 'Início', href: '/index', icon: 'fa-home' },
  { label: 'Ponza Lab', href: '/upload', icon: 'fa-upload' },
  { label: 'Cotações', href: '/quotes', icon: 'fa-file-text-o' },
  { label: 'Pacientes', href: '/catalog', icon: 'fa-users' },
  { label: 'Estoque', href: '/products', icon: 'fa-archive' },
  { label: 'Financeiro', href: '/finances', icon: 'fa-line-chart' },
  { label: 'Agenda', href: '/agenda', icon: 'fa-calendar' },
  { label: 'Pagamentos', href: '/payments', icon: 'fa-credit-card' },
]

const subscriptionPlans = [
  {
    id: 'mensal',
    title: 'Plano Mensal',
    lead: 'Flexibilidade total para clínicas que desejam crescer com liberdade.',
    price: { currency: 'R$', amount: '79,90', per: '/ mês' },
    note: 'Renovação automática mensal',
    actionLabel: 'Assinar Plano Mensal',
    href: '/subscribe_pay_mensal',
  },
  {
    id: 'anual',
    title: 'Plano Anual',
    lead: 'Economize R$ 120/ano e mantenha acesso por 12 meses.',
    price: { currency: 'R$', amount: '69,80', per: ' / mês' },
    highlight: 'Economize 12,5%',
    note: 'Equivalente a R$ 838,00/ano',
    actionLabel: 'Assinar Plano Anual',
    href: '/subscribe_pay_anual',
  },
]

const packagePlans = [
  {
    id: 'package-50',
    title: 'Pacote 50 análises',
    lead: 'Ideal para clínicas pequenas.',
    price: { currency: 'R$', amount: '120', per: '' },
    actionLabel: 'Comprar 50 análises',
    href: '/purchase_package/50',
  },
  {
    id: 'package-150',
    title: 'Pacote 150 análises',
    lead: 'Perfeito para uso regular em média escala.',
    price: { currency: 'R$', amount: '300', per: '' },
    actionLabel: 'Comprar 150 análises',
    href: '/purchase_package/150',
  },
  {
    id: 'package-500',
    title: 'Pacote 500 análises',
    lead: 'Maior custo-benefício em clínicas grandes.',
    price: { currency: 'R$', amount: '800', per: '' },
    actionLabel: 'Comprar 500 análises',
    href: '/purchase_package/500',
  },
]

export default function Payments() {
  const currentPath = typeof window !== 'undefined' ? window.location.pathname : '/payments'
  const [collapsed, setCollapsed] = useState(
    typeof window !== 'undefined' && localStorage.getItem('dashboardSidebar') === '1',
  )

  const alerts = useMemo(() => {
    if (typeof window === 'undefined') return []
    const params = new URLSearchParams(window.location.search)
    const next = []
    if (params.get('message') === 'pacote') {
      next.push({
        type: 'warning',
        text: 'Seu pacote de análises acabou. Adquira mais para continuar usando o Ponza Lab.',
      })
    }
    if (params.has('success')) {
      next.push({
        type: 'success',
        text: 'Pagamento confirmado! Sua compra foi registrada com sucesso.',
      })
    }
    if (params.has('canceled')) {
      next.push({
        type: 'error',
        text: 'Pagamento cancelado. Se precisar de ajuda, fale com nosso time.',
      })
    }
    if (params.get('error') === 'checkout_unavailable') {
      next.push({
        type: 'error',
        text: 'Pagamento indisponível no momento. Fale com o suporte.',
      })
    }
    if (params.get('error') === 'checkout_error') {
      next.push({
        type: 'error',
        text: 'Não foi possível iniciar o checkout agora. Tente novamente.',
      })
    }
    return next
  }, [])

  const handleToggleSidebar = () => {
    const next = !collapsed
    setCollapsed(next)
    localStorage.setItem('dashboardSidebar', next ? '1' : '0')
  }

  const isActiveLink = (href) => {
    const resolved = resolvePath(href)
    if (resolved === '/catalog') {
      return (
        currentPath.startsWith('/catalog') ||
        currentPath.startsWith('/edit_patient') ||
        currentPath.startsWith('/patient_info')
      )
    }
    if (resolved === '/quotes') {
      return currentPath.startsWith('/quotes')
    }
    if (resolved === '/products') {
      return currentPath.startsWith('/products')
    }
    return currentPath === resolved
  }

  return (
    <div className={`dashboard-shell ${collapsed ? 'is-collapsed' : ''}`}>
      <aside className="dashboard-sidebar">
        <div className="dashboard-sidebar__brand">
          
          <div className="dashboard-logo-wrap">
            <img src="/static/images/5.svg" alt="Ponza Health" className="dashboard-logo dashboard-logo--full" />
            <img src="/static/images/15.svg" alt="Ponza Health" className="dashboard-logo dashboard-logo--compact" />
          </div>
          <button className="dashboard-toggle" type="button" onClick={handleToggleSidebar} aria-label="Alternar menu">
            <i className="fa fa-bars" />
          </button>
        </div>
        <nav className="dashboard-nav" aria-label="Menu principal">
          {navItems.map((item) => (
            <a
              key={item.href}
              className={`dashboard-link ${isActiveLink(item.href) ? 'is-active' : ''}`}
              href={item.href}
              data-tooltip={item.label}
            >
              <i className={`fa ${item.icon}`} aria-hidden="true" />
              <span>{item.label}</span>
            </a>
          ))}
        </nav>
        <div className="dashboard-sidebar__footer">
          <a className="dashboard-link is-logout" href={withBackend('/logout')} data-tooltip="Sair">
            <i className="fa fa-sign-out" aria-hidden="true" />
            <span>Sair</span>
          </a>
        </div>
      </aside>

      <main className="dashboard-main">
        <header className="dashboard-header">
          <div>
            <p className="dashboard-kicker">Pagamentos</p>
            <h1>Planos e pacotes da sua clínica</h1>
            <p className="dashboard-subtitle">
              Escolha o plano ideal e complemente com pacotes de análises conforme a demanda.
            </p>
          </div>
          <div className="dashboard-actions">
            <a className="dashboard-icon-btn" href="/account" aria-label="Minha conta">
              <i className="fa fa-user" aria-hidden="true" />
            </a>
            <button className="dashboard-icon-btn" type="button" aria-label="Notificações">
              <i className="fa fa-bell" aria-hidden="true" />
            </button>
          </div>
        </header>

        {alerts.map((alert) => (
          <div
            key={alert.text}
            className={`dashboard-alert ${alert.type === 'success' ? 'dashboard-alert--success' : ''}`}
          >
            {alert.text}
          </div>
        ))}

        <section className="payments-section">
          <div className="payments-section__intro">
            <p className="dashboard-kicker">Planos de assinatura</p>
            <h2>Assinaturas recorrentes</h2>
            <p className="dashboard-subtitle">
              Mantenha acesso completo ao sistema com atualizações e suporte contínuo.
            </p>
          </div>
          <div className="pricing-grid">
            {subscriptionPlans.map((plan) => (
              <article key={plan.id} className={`pricing-card ${plan.highlight ? 'is-featured' : ''}`}>
                <div className="pricing-card-head">
                  <div className="pricing-title-row">
                    <h3>{plan.title}</h3>
                    {plan.highlight ? <span className="pricing-badge">{plan.highlight}</span> : null}
                  </div>
                  <p className="pricing-lead">{plan.lead}</p>
                </div>
                <div className="plan-price">
                  <span className="price-currency">{plan.price.currency}</span>
                  <strong>{plan.price.amount}</strong>
                  <span>{plan.price.per}</span>
                </div>
                <p className="payments-note">{plan.note}</p>
                <div className="plan-actions">
                  <a
                    className="btn-primary"
                    href={withBackend(plan.href)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {plan.actionLabel}
                  </a>
                </div>
              </article>
            ))}
          </div>
        </section>

        <section className="payments-section">
          <div className="payments-section__intro">
            <p className="dashboard-kicker">Pacotes de análises</p>
            <h2>Recarregue créditos do Ponza Lab</h2>
            <p className="dashboard-subtitle">
              Pacotes adicionais para manter o ritmo dos exames e relatórios enviados.
            </p>
          </div>
          <div className="pricing-grid">
            {packagePlans.map((plan) => (
              <article key={plan.id} className="pricing-card">
                <div className="pricing-card-head">
                  <h3>{plan.title}</h3>
                  <p className="pricing-lead">{plan.lead}</p>
                </div>
                <div className="plan-price">
                  <span className="price-currency">{plan.price.currency}</span>
                  <strong>{plan.price.amount}</strong>
                  {plan.price.per ? <span>{plan.price.per}</span> : null}
                </div>
                <div className="plan-actions">
                  <a
                    className="btn-primary"
                    href={withBackend(plan.href)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {plan.actionLabel}
                  </a>
                </div>
              </article>
            ))}
          </div>
        </section>
      </main>
    </div>
  )
}

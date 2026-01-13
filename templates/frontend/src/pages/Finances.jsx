import { useMemo, useState } from 'react'
import { buildCacheKey, readCache, writeCache } from '../utils/cache'

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

const formatCurrency = (value) =>
  new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL', minimumFractionDigits: 2 }).format(
    Number(value) || 0,
  )

const BarChart = ({ data }) => {
  const max = Math.max(...data.map((item) => item.value), 1)
  return (
    <div className="finance-bars">
      {data.map((item) => (
        <div key={item.label} className="finance-bar">
          <div
            className="finance-bar__fill"
            style={{ height: `${(item.value / max) * 100}%`, background: item.color || '#0f63ff' }}
            title={`${item.label}: ${formatCurrency(item.value)}`}
          />
          <span className="finance-bar__label">{item.label}</span>
        </div>
      ))}
    </div>
  )
}

export default function Finances() {
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('dashboardSidebar') === '1')
  const [cashboxFilter, setCashboxFilter] = useState('all')
  const [timeframe, setTimeframe] = useState('30d')

  const sidebarNav = useMemo(() => navItems, [])
  const isActiveLink = (href) => {
    const resolved = resolvePath(href)
    const current = window.location.pathname.replace(/\/$/, '') || '/'
    if (resolved === '/quotes') {
      return current.startsWith('/quotes')
    }
    return current === resolved
  }

  const stats = useMemo(
    () => ({
      currentCash: 48250.75,
      open: 3,
      closed: 5,
      total: 8,
      mrr: 61200,
      burn: -21800,
    }),
    [],
  )

  const barData = useMemo(
    () => [
      { label: 'Jan', value: 18000, color: '#0f63ff' },
      { label: 'Fev', value: 22000, color: '#10b981' },
      { label: 'Mar', value: 19500, color: '#f59e0b' },
      { label: 'Abr', value: 25500, color: '#6366f1' },
      { label: 'Mai', value: 26800, color: '#ec4899' },
      { label: 'Jun', value: 24200, color: '#14b8a6' },
    ],
    [],
  )

  const kpis = useMemo(
    () => [
      { label: 'MRR', value: stats.mrr, trend: '+8,4%', tone: 'positive' },
      { label: 'Burn mensal', value: stats.burn, trend: '-5,1%', tone: 'neutral' },
      { label: 'Ticket médio', value: 420, trend: '+2,3%', tone: 'positive' },
      { label: 'Recebíveis 7d', value: 18200, trend: '+R$ 3,1k', tone: 'positive' },
    ],
    [stats.burn, stats.mrr],
  )

  const cashboxes = useMemo(
    () => [
      { id: 'CX-104', name: 'Recepção', status: 'Aberto', balance: 12500.25, owner: 'Ana' },
      { id: 'CX-087', name: 'Laboratório', status: 'Aberto', balance: 8200.1, owner: 'João' },
      { id: 'CX-065', name: 'Online', status: 'Fechado', balance: 21400.9, owner: 'Equipe' },
      { id: 'CX-033', name: 'Cartão', status: 'Fechado', balance: 9800.0, owner: 'Equipe' },
    ],
    [],
  )

  const filteredCashboxes = cashboxes.filter((c) => {
    if (cashboxFilter === 'open') return c.status === 'Aberto'
    if (cashboxFilter === 'closed') return c.status === 'Fechado'
    return true
  })

  const analytics = useMemo(
    () => [
      {
        title: 'Fluxo diário',
        detail: 'Picos de receita vs. despesas fixas e variáveis com alerta de stress de caixa.',
        tag: 'Tendência',
      },
      {
        title: 'Receita por canal',
        detail: 'Presencial, online e cartões com variação semanal e margem unitária.',
        tag: 'Segmentação',
      },
      {
        title: 'Despesas recorrentes',
        detail: 'Assinaturas, folha e fornecedores com previsão de vencimento.',
        tag: 'Controle',
      },
      {
        title: 'Margem e rentabilidade',
        detail: 'Margem bruta/líquida por centro de custo e serviço.',
        tag: 'Rentabilidade',
      },
    ],
    [],
  )

  const receivables = useMemo(
    () => [
      { label: 'Convênios', value: 14200, due: 'Próximos 7d', tone: 'positive' },
      { label: 'Cartão', value: 8200, due: 'D+2', tone: 'info' },
      { label: 'Particular', value: 6200, due: 'Hoje', tone: 'warn' },
    ],
    [],
  )

  const cashflow = useMemo(
    () => [
      { label: 'Entradas', value: 42800, detail: '+12% vs último ciclo', tone: 'positive' },
      { label: 'Saídas', value: 19800, detail: '-4% vs último ciclo', tone: 'neutral' },
      { label: 'Resultado', value: 23000, detail: 'Margem 53,7%', tone: 'positive' },
    ],
    [],
  )

  return (
    <div className={`dashboard-shell ${collapsed ? 'is-collapsed' : ''}`}>
      <aside className="dashboard-sidebar">
        <div className="dashboard-sidebar__brand">
          <div className="dashboard-logo-wrap">
            <img src="/static/images/5.svg" alt="Ponza Health" className="dashboard-logo dashboard-logo--full" />
            <img src="/static/images/15.svg" alt="Ponza Health" className="dashboard-logo dashboard-logo--compact" />
          </div>
          <button
            className="dashboard-toggle"
            type="button"
            onClick={() => {
              const next = !collapsed
              setCollapsed(next)
              localStorage.setItem('dashboardSidebar', next ? '1' : '0')
            }}
            aria-label="Alternar menu"
          >
            <i className="fa fa-bars" />
          </button>
        </div>
        <nav className="dashboard-nav" aria-label="Menu principal">
          {sidebarNav.map((item) => (
            <a
              key={item.href}
              className={`dashboard-link ${isActiveLink(item.href) ? 'is-active' : ''}`}
              href={withBackend(item.href)}
            >
              <i className={`fa ${item.icon}`} aria-hidden="true" />
              <span>{item.label}</span>
            </a>
          ))}
        </nav>
        <div className="dashboard-sidebar__footer">
          <a className="dashboard-link is-logout" href={withBackend('/logout')}>
            <i className="fa fa-sign-out" aria-hidden="true" />
            <span>Sair</span>
          </a>
        </div>
      </aside>

      <main className="dashboard-main finance-surface">
        <section className="finance-hero">
          <div className="finance-hero__header">
            <span className="finance-pill">Saúde financeira</span>
            <h1>Radar financeiro</h1>
            <p className="finance-lead">
              Visão unificada de caixa, recebíveis e desempenho. Acompanhe picos, proteja margem e aja rápido.
            </p>
            <div className="finance-hero__actions">
              <button type="button" className="btn-primary">Exportar CSV</button>
              <button type="button" className="btn-outline">Compartilhar snapshot</button>
            </div>
          </div>
          <div className="finance-hero__kpis">
            <div className="finance-stat">
              <p>Caixa atual</p>
              <strong>{formatCurrency(stats.currentCash)}</strong>
              <small>Disponível agora</small>
            </div>
            <div className="finance-stat">
              <p>Caixas</p>
              <strong>{stats.open} abertos / {stats.total}</strong>
              <small>{stats.closed} encerrados</small>
            </div>
            <div className="finance-stat">
              <p>Período</p>
              <div className="finance-timeframe">
                {['7d', '30d', '90d'].map((option) => (
                  <button
                    key={option}
                    type="button"
                    className={`finance-chip ${timeframe === option ? 'is-active' : ''}`}
                    onClick={() => setTimeframe(option)}
                  >
                    {option}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </section>

        <div className="finance-grid finance-grid--kpis">
          {kpis.map((item) => (
            <article className="finance-card" key={item.label}>
              <div className="finance-card__meta">
                <span className={`finance-dot finance-dot--${item.tone}`} />
                <span className="finance-card__label">{item.label}</span>
              </div>
              <div className="finance-card__value">{formatCurrency(item.value)}</div>
              <p className={`finance-card__trend finance-card__trend--${item.tone}`}>{item.trend}</p>
            </article>
          ))}
        </div>

        <div className="finance-grid finance-grid--wide">
          <section className="finance-panel">
            <header className="finance-panel__head">
              <div>
                <p className="finance-panel__eyebrow">Receita</p>
                <h2>Curva de entradas</h2>
              </div>
              <div className="finance-legend">
                <span className="legend-dot legend-dot--blue" /> Entradas
                <span className="legend-dot legend-dot--green" /> Meta
              </div>
            </header>
            <BarChart data={barData} />
          </section>

          <section className="finance-panel finance-panel--stacked">
            <header className="finance-panel__head">
              <div>
                <p className="finance-panel__eyebrow">Fluxo</p>
                <h2>Entradas vs saídas</h2>
              </div>
            </header>
            <div className="finance-flow">
              {cashflow.map((item) => (
                <div key={item.label} className="finance-flow__item">
                  <div className="finance-card__meta">
                    <span className={`finance-dot finance-dot--${item.tone}`} />
                    <span>{item.label}</span>
                  </div>
                  <strong>{formatCurrency(item.value)}</strong>
                  <small>{item.detail}</small>
                </div>
              ))}
            </div>
            <div className="finance-receivables">
              {receivables.map((item) => (
                <div key={item.label} className="finance-receivable">
                  <div>
                    <p className="finance-receivable__label">{item.label}</p>
                    <small>{item.due}</small>
                  </div>
                  <div className={`finance-receivable__value finance-receivable__value--${item.tone}`}>
                    {formatCurrency(item.value)}
                  </div>
                </div>
              ))}
            </div>
          </section>
        </div>

        <section className="finance-panel">
          <header className="finance-panel__head">
            <div>
              <p className="finance-panel__eyebrow">Caixas</p>
              <h2>Controle por canal</h2>
            </div>
            <div className="finance-filters">
              <label className="dashboard-field">
                <span>Filtro</span>
                <select
                  className="dashboard-select"
                  value={cashboxFilter}
                  onChange={(event) => setCashboxFilter(event.target.value)}
                >
                  <option value="all">Todos</option>
                  <option value="open">Abertos</option>
                  <option value="closed">Fechados</option>
                </select>
              </label>
            </div>
          </header>
          <div className="finance-table">
            <div className="finance-table__head">
              <span>ID</span>
              <span>Nome</span>
              <span>Status</span>
              <span>Responsável</span>
              <span>Saldo</span>
            </div>
            {filteredCashboxes.map((cb) => (
              <div className="finance-table__row" key={cb.id}>
                <span>{cb.id}</span>
                <span>{cb.name}</span>
                <span className={cb.status === 'Aberto' ? 'tag tag--success' : 'tag tag--neutral'}>{cb.status}</span>
                <span>{cb.owner}</span>
                <span>{formatCurrency(cb.balance)}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="finance-panel">
          <header className="finance-panel__head">
            <div>
              <p className="finance-panel__eyebrow">Insights</p>
              <h2>Relatórios analíticos</h2>
            </div>
          </header>
          <div className="report-grid">
            {analytics.map((item) => (
              <article className="report-card" key={item.title}>
                <header className="report-card__header">
                  <span className="tag tag--info">{item.tag}</span>
                  <h3>{item.title}</h3>
                </header>
                <p className="report-card__desc">{item.detail}</p>
                <button type="button" className="btn-secondary btn-small">Ver detalhes</button>
              </article>
            ))}
          </div>
        </section>
      </main>
    </div>
  )
}

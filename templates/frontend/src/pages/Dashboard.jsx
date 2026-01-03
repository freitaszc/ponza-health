import { useEffect, useMemo, useState } from 'react'
import { buildCacheKey, readCache, writeCache } from '../utils/cache'

const emptyDashboard = {
  username: '',
  total_patients: 0,
  total_consults: 0,
  used: 0,
  remaining: 0,
  package_total: 0,
  patients_new_30: 0,
  patients_return_30: 0,
  insurance_particular_30: 0,
  insurance_convenio_30: 0,
  consults_week_series: [],
  pdf_analyses_last7: [],
  low_stock: [],
  quotes_items: [],
  quotes_total: 0,
  quotes_responded: 0,
  quotes_pending: 0,
  notifications_unread: 0,
  trial_active: false,
}

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
  { label: 'Agenda', href: '/agenda', icon: 'fa-calendar' },
  { label: 'Pagamentos', href: '/payments', icon: 'fa-credit-card' },
]

const formatNumber = (value) => new Intl.NumberFormat('pt-BR').format(value || 0)

const buildWeekLabels = () => {
  const out = []
  const now = new Date()
  for (let i = 6; i >= 0; i -= 1) {
    const d = new Date(now)
    d.setDate(now.getDate() - i)
    const label = `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}`
    out.push(label)
  }
  return out
}

const buildFallbackSeries = (keys) =>
  buildWeekLabels().map((label) => ({ d: label, ...keys }))

function DonutChart({ segments, size = 56, stroke = 7 }) {
  const radius = (size - stroke) / 2
  const innerRadius = Math.max(radius - stroke * 0.75, 0)
  const backdropRadius = Math.min(radius + stroke * 0.3, size / 2)
  const circumference = 2 * Math.PI * radius
  const total = segments.reduce((sum, segment) => sum + segment.value, 0)
  let offset = 0

  return (
    <svg className="donut-chart" width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img">
      <circle className="donut-chart__backdrop" cx={size / 2} cy={size / 2} r={backdropRadius} />
      <circle
        className="donut-chart__track"
        cx={size / 2}
        cy={size / 2}
        r={radius}
        strokeWidth={stroke}
      />
      <g transform={`rotate(-90 ${size / 2} ${size / 2})`}>
        {segments.map((segment, index) => {
          const value = total > 0 ? segment.value : 0
          const dash = total > 0 ? (value / total) * circumference : 0
          const dashOffset = circumference * 0.25 - offset
          offset += dash
          return (
            <circle
              key={`${segment.label}-${index}`}
              cx={size / 2}
              cy={size / 2}
              r={radius}
              strokeWidth={stroke}
              stroke={segment.color}
              strokeDasharray={`${dash} ${circumference - dash}`}
              strokeDashoffset={dashOffset}
              strokeLinecap="round"
              className="donut-chart__segment"
            />
          )
        })}
      </g>
      {innerRadius > 0 ? (
        <circle className="donut-chart__center" cx={size / 2} cy={size / 2} r={innerRadius} />
      ) : null}
    </svg>
  )
}

function StackedBars({ data }) {
  const maxValue = Math.max(
    ...data.map((item) => item.primeira + item.retorno),
    1,
  )

  return (
    <div className="stacked-bars">
      {data.map((item) => {
        const total = item.primeira + item.retorno
        const height = (total / maxValue) * 100
        return (
          <div className="stacked-bar" key={item.d}>
            <div
              className="stacked-bar__fill"
              style={{ height: `${height}%` }}
              title={`${item.d}: ${item.primeira} primeiras, ${item.retorno} retornos`}
            >
              <span className="stacked-bar__segment segment--primary" style={{ flex: item.primeira }} />
              <span className="stacked-bar__segment segment--secondary" style={{ flex: item.retorno }} />
            </div>
            <span className="stacked-bar__label">{item.d}</span>
          </div>
        )
      })}
    </div>
  )
}

function AreaChart({ data }) {
  const width = 640
  const height = 240
  const padding = 28
  const maxValue = Math.max(...data.map((item) => item.count), 1)

  const points = data.map((item, index) => {
    const x = padding + (index / (data.length - 1 || 1)) * (width - padding * 2)
    const y = height - padding - (item.count / maxValue) * (height - padding * 2)
    return { x, y, label: item.d, value: item.count }
  })

  const linePath = points
    .map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x} ${point.y}`)
    .join(' ')

  const lastPoint = points[points.length - 1] || { x: width - padding }
  const firstPoint = points[0] || { x: padding }
  const areaPath = `${linePath} L ${lastPoint.x} ${height - padding} L ${firstPoint.x} ${height - padding} Z`

  return (
    <div className="area-chart">
      <svg viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
        <defs>
          <linearGradient id="areaGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#0b3f8f" stopOpacity="0.45" />
            <stop offset="55%" stopColor="#0f63ff" stopOpacity="0.18" />
            <stop offset="100%" stopColor="#0f63ff" stopOpacity="0.03" />
          </linearGradient>
          <linearGradient id="areaLineGradient" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#0b3f8f" />
            <stop offset="55%" stopColor="#0f63ff" />
            <stop offset="100%" stopColor="#4f9cff" />
          </linearGradient>
        </defs>
        <g className="area-chart__grid">
          {[0.25, 0.5, 0.75].map((ratio) => (
            <line
              key={ratio}
              x1={padding}
              x2={width - padding}
              y1={padding + (height - padding * 2) * ratio}
              y2={padding + (height - padding * 2) * ratio}
            />
          ))}
        </g>
        <path d={areaPath} fill="url(#areaGradient)" />
        <path d={linePath} className="area-chart__line" stroke="url(#areaLineGradient)" />
        {points.map((point) => (
          <circle
            key={`${point.label}-${point.value}`}
            cx={point.x}
            cy={point.y}
            r="4"
            className="area-chart__dot"
          />
        ))}
      </svg>
      <div className="area-chart__labels">
        {data.map((item) => (
          <span key={item.d}>{item.d}</span>
        ))}
      </div>
    </div>
  )
}

export default function Dashboard() {
  const [data, setData] = useState(emptyDashboard)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('dashboardSidebar') === '1')
  const currentPath = typeof window !== 'undefined' ? window.location.pathname : '/index'
  const dashboardCacheKey = useMemo(() => buildCacheKey('dashboard', ['summary']), [])

  useEffect(() => {
    let active = true
    const cached = readCache(dashboardCacheKey)
    if (cached) {
      setData({ ...emptyDashboard, ...cached })
      setLoading(false)
    } else {
      setLoading(true)
    }
    fetch('/api/dashboard', { credentials: 'same-origin' })
      .then((response) => {
        if (!response.ok) {
          throw new Error('Falha ao carregar o dashboard.')
        }
        return response.json()
      })
      .then((payload) => {
        if (!active) return
        setData({ ...emptyDashboard, ...payload })
        writeCache(dashboardCacheKey, payload)
        setError('')
      })
      .catch(() => {
        if (!active) return
        setError('Não foi possível carregar os dados do dashboard.')
      })
      .finally(() => {
        if (!active) return
        setLoading(false)
      })

    return () => {
      active = false
    }
  }, [dashboardCacheKey])

  const consultationSeries = useMemo(() => {
    if (data.consults_week_series?.length) {
      return data.consults_week_series
    }
    return buildFallbackSeries({ primeira: 0, retorno: 0 })
  }, [data.consults_week_series])

  const pdfSeries = useMemo(() => {
    if (data.pdf_analyses_last7?.length) {
      return data.pdf_analyses_last7
    }
    return buildFallbackSeries({ count: 0 })
  }, [data.pdf_analyses_last7])

  const packageTotal = data.package_total || data.used + data.remaining
  const packagePercent = packageTotal > 0 ? Math.round((data.used / packageTotal) * 100) : 0
  const patientsTotal = data.patients_new_30 + data.patients_return_30
  const paymentsTotal = data.insurance_particular_30 + data.insurance_convenio_30

  const donutPackages = [
    { label: 'Usado', value: data.used, color: '#0f63ff' },
    { label: 'Disponível', value: data.remaining, color: '#dbeafe' },
  ]

  const donutPatients = [
    { label: 'Novos', value: data.patients_new_30, color: '#0ea5e9' },
    { label: 'Recorrentes', value: data.patients_return_30, color: '#94a3b8' },
  ]

  const donutPayments = [
    { label: 'Particular', value: data.insurance_particular_30, color: '#6366f1' },
    { label: 'Convênio', value: data.insurance_convenio_30, color: '#c4b5fd' },
  ]

  const sidebarNav = navItems

  const handleToggleSidebar = () => {
    const next = !collapsed
    setCollapsed(next)
    localStorage.setItem('dashboardSidebar', next ? '1' : '0')
  }

  return (
    <div className={`dashboard-shell ${collapsed ? 'is-collapsed' : ''}`}>
      <aside className="dashboard-sidebar">
        <div className="dashboard-sidebar__brand">
          
          <div className="dashboard-logo-wrap">
            <img src="/static/images/5.svg" alt="Ponza Health" className="dashboard-logo dashboard-logo--full" />
            <img src="/static/images/15.svg" alt="Ponza Health" className="dashboard-logo dashboard-logo--compact" />
          </div>
          <div className="dashboard-title">
          </div>
          <button className="dashboard-toggle" type="button" onClick={handleToggleSidebar} aria-label="Alternar menu">
            <i className="fa fa-bars" />
          </button>
        </div>
        <nav className="dashboard-nav" aria-label="Menu principal">
          {sidebarNav.map((item) => (
            <a
              key={item.href}
              className={`dashboard-link ${currentPath === resolvePath(item.href) ? 'is-active' : ''}`}
              href={item.href}
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

      <main className="dashboard-main">
        <header className="dashboard-header">
          <div>
            <p className="dashboard-kicker">Painel de controle</p>
            <h1>Bem-vindo(a), {data.username}</h1>
          </div>
          <div className="dashboard-actions">
            <a className="dashboard-icon-btn" href="/account" aria-label="Minha conta">
              <i className="fa fa-user" aria-hidden="true" />
            </a>
            <button className="dashboard-icon-btn" type="button" aria-label="Notificações">
              <i className="fa fa-bell" aria-hidden="true" />
              {data.notifications_unread ? <span className="badge">{data.notifications_unread}</span> : null}
            </button>
          </div>
        </header>

        {data.trial_active ? (
          <div className="dashboard-banner">
            <span>
              Você está no <strong>período de teste</strong>. Garanta acesso contínuo ativando seu plano.
            </span>
            <a href="/payments">Fazer upgrade</a>
          </div>
        ) : null}

        {error ? <div className="dashboard-alert">{error}</div> : null}

        <section className="dashboard-metrics">
          <div className="dashboard-card metric-card">
            <div className="metric-card__head">
              <div className="metric-icon metric-icon--packages">
                <i className="fa fa-flask" aria-hidden="true" />
              </div>
              <div>
                <p className="card-title">Pacotes de análise</p>
                <h3>{packagePercent}% usados</h3>
              </div>
            </div>
            <div className="metric-body">
              <DonutChart segments={donutPackages} />
              <div className="metric-list">
                <span>
                  <i className="dot dot--primary" /> Usado: {formatNumber(data.used)}
                </span>
                <span>
                  <i className="dot dot--muted" /> Disponível: {formatNumber(data.remaining)}
                </span>
              </div>
            </div>
            <a className="metric-link" href="/payments">
              Comprar pacotes
            </a>
          </div>

          <div className="dashboard-card metric-card">
            <div className="metric-card__head">
              <div className="metric-icon metric-icon--patients">
                <i className="fa fa-users" aria-hidden="true" />
              </div>
              <div>
                <p className="card-title">Pacientes (30 dias)</p>
                <h3>{formatNumber(patientsTotal)}</h3>
              </div>
            </div>
            <div className="metric-body">
              <DonutChart segments={donutPatients} />
              <div className="metric-list">
                <span>
                  <i className="dot dot--accent" /> Novos: {formatNumber(data.patients_new_30)}
                </span>
                <span>
                  <i className="dot dot--soft" /> Recorrentes: {formatNumber(data.patients_return_30)}
                </span>
              </div>
            </div>
          </div>

          <div className="dashboard-card metric-card">
            <div className="metric-card__head">
              <div className="metric-icon metric-icon--payments">
                <i className="fa fa-credit-card" aria-hidden="true" />
              </div>
              <div>
                <p className="card-title">Pagamentos (30 dias)</p>
                <h3>{formatNumber(paymentsTotal)}</h3>
              </div>
            </div>
            <div className="metric-body">
              <DonutChart segments={donutPayments} />
              <div className="metric-list">
                <span>
                  <i className="dot dot--violet" /> Particular: {formatNumber(data.insurance_particular_30)}
                </span>
                <span>
                  <i className="dot dot--violet-soft" /> Convênio: {formatNumber(data.insurance_convenio_30)}
                </span>
              </div>
            </div>
          </div>

          <div className="dashboard-card metric-card metric-card--chart">
            <div className="metric-card__head">
              <div className="metric-icon metric-icon--consults">
                <i className="fa fa-calendar-check-o" aria-hidden="true" />
              </div>
              <div>
                <p className="card-title">Consultas (últimos 7 dias)</p>
                <h3>{formatNumber(consultationSeries.reduce((sum, item) => sum + item.primeira + item.retorno, 0))}</h3>
              </div>
            </div>
            <StackedBars data={consultationSeries} />
            <div className="metric-legend">
              <span>
                <i className="dot dot--primary" /> Primeira
              </span>
              <span>
                <i className="dot dot--secondary" /> Retorno
              </span>
            </div>
          </div>
        </section>

        <section className="dashboard-grid">
          <div className="dashboard-card chart-card">
            <div className="chart-card__head">
              <div>
                <p className="card-title">Análises de PDFs (7 dias)</p>
                <h3>{formatNumber(pdfSeries.reduce((sum, item) => sum + item.count, 0))} análises</h3>
              </div>
            </div>
            <AreaChart data={pdfSeries} />
          </div>

          <div className="dashboard-side">
            <div className="dashboard-card table-card">
              <div className="table-card__head">
                <div className="table-card__title">
                  <span className="table-card__icon" aria-hidden="true">
                    <i className="fa fa-archive" />
                  </span>
                  <p className="card-title">Estoque baixo</p>
                </div>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Produto</th>
                      <th>Qtd.</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.low_stock?.length ? (
                      data.low_stock.map((item) => (
                        <tr key={item.name}>
                          <td>{item.name}</td>
                          <td>{formatNumber(item.quantity)}</td>
                        </tr>
                      ))
                    ) : (
                      <tr>
                        <td colSpan="2">Nenhum produto abaixo do nível mínimo.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="dashboard-card table-card">
              <div className="table-card__head">
                <div className="table-card__title">
                  <span className="table-card__icon" aria-hidden="true">
                    <i className="fa fa-check-circle" />
                  </span>
                  <p className="card-title">Cotações respondidas</p>
                </div>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Cotação</th>
                      <th>Respostas</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.quotes_items?.length ? (
                      data.quotes_items.map((item) => (
                        <tr key={item.name}>
                          <td>{item.name}</td>
                          <td>{formatNumber(item.responses)}</td>
                        </tr>
                      ))
                    ) : (
                      <tr>
                        <td colSpan="2">Nenhuma cotação encontrada.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              <div className="table-summary">
                Respondidas: {formatNumber(data.quotes_responded)} • Pendentes: {formatNumber(data.quotes_pending)}
              </div>
            </div>
          </div>
        </section>

        {loading ? <div className="dashboard-loading">Atualizando métricas…</div> : null}
      </main>
    </div>
  )
}

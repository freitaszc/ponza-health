import { useEffect, useMemo, useState } from 'react'
import { useRouter } from '../components/Router'
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
  { label: 'Agenda', href: '/agenda', icon: 'fa-calendar' },
  { label: 'Pagamentos', href: '/payments', icon: 'fa-credit-card' },
]

export default function QuoteResults() {
  const { params } = useRouter()
  const quoteId = params?.quoteId
  const currentPath = typeof window !== 'undefined' ? window.location.pathname : '/quotes'

  const [collapsed, setCollapsed] = useState(
    typeof window !== 'undefined' && localStorage.getItem('dashboardSidebar') === '1',
  )
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const sidebarNav = useMemo(() => navItems, [])
  const isActiveLink = (href) => {
    const resolved = resolvePath(href)
    if (resolved === '/quotes') {
      return currentPath.startsWith('/quotes')
    }
    if (resolved === '/catalog') {
      return (
        currentPath.startsWith('/catalog') ||
        currentPath.startsWith('/edit_patient') ||
        currentPath.startsWith('/patient_info')
      )
    }
    return currentPath === resolved
  }

  useEffect(() => {
    let active = true
    const load = async () => {
      const cacheKey = buildCacheKey('quote-results', [quoteId || 'unknown'])
      const cached = readCache(cacheKey)
      if (cached) {
        setData(cached)
        setLoading(false)
      } else {
        setLoading(true)
      }
      setError('')
      try {
        const response = await fetch(`/api/quotes/${quoteId}/results`, { credentials: 'include' })
        const payload = await response.json().catch(() => ({}))
        if (!response.ok || payload?.success === false) {
          throw new Error(payload?.error || 'Não foi possivel carregar a cotação.')
        }
        if (!active) return
        setData(payload)
        writeCache(cacheKey, payload)
      } catch (err) {
        if (!active) return
        setError(err.message || 'Não foi possivel carregar a cotação.')
      } finally {
        if (!active) return
        setLoading(false)
      }
    }
    if (quoteId) {
      load()
    }
    return () => {
      active = false
    }
  }, [quoteId])

  const handleToggleSidebar = () => {
    const next = !collapsed
    setCollapsed(next)
    localStorage.setItem('dashboardSidebar', next ? '1' : '0')
  }

  const items = data?.items || []
  const suppliers = data?.suppliers || []
  const responses = data?.responses || {}
  const bestPerItem = data?.best_per_item || {}

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
          {sidebarNav.map((item) => (
            <a
              key={item.href}
              className={`dashboard-link ${isActiveLink(item.href) ? 'is-active' : ''}`}
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
            <p className="dashboard-kicker">Comparativo</p>
            <h1>{data?.quote?.title || 'cotação'}</h1>
            <p className="dashboard-subtitle">Veja o melhor custo por item.</p>
          </div>
          <div className="dashboard-actions">
            <a className="dashboard-icon-btn" href="/quotes" aria-label="Voltar">
              <i className="fa fa-arrow-left" aria-hidden="true" />
            </a>
          </div>
        </header>

        {error ? <div className="dashboard-alert">{error}</div> : null}
        {loading ? <div className="dashboard-loading">Carregando comparativo...</div> : null}

        {!loading ? (
          <div className="data-table data-table--compare data-table--dashboard">
            <table>
              <thead>
                <tr>
                  <th>Item</th>
                  {suppliers.map((supplier) => (
                    <th key={supplier.id}>{supplier.name}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {items.length ? (
                  items.map((item, idx) => (
                    <tr key={`${item}-${idx}`}>
                      <td>
                        <strong>{item}</strong>
                      </td>
                      {suppliers.map((supplier) => {
                        const answer = responses?.[supplier.id]?.[idx]
                        const isBest = String(bestPerItem?.[idx]) === String(supplier.id)
                        return (
                          <td key={`${supplier.id}-${idx}`} className={isBest ? 'quote-best' : ''}>
                            {answer ? (
                              <div className="quote-cell">
                                {isBest ? <span className="quote-badge">Menor preco</span> : null}
                                <span className="quote-price">{answer.price ? `R$ ${answer.price}` : '—'}</span>
                                <span className="quote-deadline">{answer.deadline ? `${answer.deadline} dias` : '—'}</span>
                              </div>
                            ) : (
                              <span className="muted">—</span>
                            )}
                          </td>
                        )
                      })}
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={suppliers.length + 1} className="empty-cell">
                      Nenhum item nesta cotação.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        ) : null}

        {!loading ? (
          <div className="form-actions">
            <a className="btn-outline" href="/quotes">Voltar</a>
            {quoteId ? (
              <a className="btn-primary" href={`/quotes/${quoteId}`}>
                Ver resumo
              </a>
            ) : null}
          </div>
        ) : null}
      </main>
    </div>
  )
}

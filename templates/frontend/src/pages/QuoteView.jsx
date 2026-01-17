import { useEffect, useMemo, useState } from 'react'
import { Link, useRouter } from '../components/Router'
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

export default function QuoteView() {
  const { params } = useRouter()
  const quoteId = params?.quoteId
  const currentPath = typeof window !== 'undefined' ? window.location.pathname : '/quotes'

  const summaryCacheKey = useMemo(
    () => buildCacheKey('quote-view', [quoteId || 'unknown']),
    [quoteId],
  )
  const resultsCacheKey = useMemo(
    () => buildCacheKey('quote-results', [quoteId || 'unknown']),
    [quoteId],
  )
  const initialSummary = useMemo(() => readCache(summaryCacheKey), [summaryCacheKey])
  const initialResults = useMemo(() => readCache(resultsCacheKey), [resultsCacheKey])

  const [collapsed, setCollapsed] = useState(
    typeof window !== 'undefined' && localStorage.getItem('dashboardSidebar') === '1',
  )
  const [data, setData] = useState(() => initialSummary || null)
  const [loading, setLoading] = useState(() => !initialSummary)
  const [error, setError] = useState('')
  const [resultsData, setResultsData] = useState(() => initialResults || null)
  const [resultsLoading, setResultsLoading] = useState(() => !initialResults)
  const [resultsError, setResultsError] = useState('')

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
    const loadSummary = async () => {
      const cached = readCache(summaryCacheKey)
      if (cached) {
        setData(cached)
        setLoading(false)
      } else {
        setLoading(true)
      }
      setError('')
      try {
        const response = await fetch(`/api/quotes/${quoteId}`, { credentials: 'include' })
        const payload = await response.json().catch(() => ({}))
        if (!response.ok || payload?.success === false) {
          throw new Error(payload?.error || 'Não foi possivel carregar a cotação.')
        }
        if (!active) return
        setData(payload)
        writeCache(summaryCacheKey, payload)
      } catch (err) {
        if (!active) return
        setError(err.message || 'Não foi possivel carregar a cotação.')
      } finally {
        if (!active) return
        setLoading(false)
      }
    }

    const loadResults = async () => {
      const cached = readCache(resultsCacheKey)
      if (cached) {
        setResultsData(cached)
        setResultsLoading(false)
      } else {
        setResultsLoading(true)
      }
      setResultsError('')
      try {
        const response = await fetch(`/api/quotes/${quoteId}/results`, { credentials: 'include' })
        const payload = await response.json().catch(() => ({}))
        if (!response.ok || payload?.success === false) {
          throw new Error(payload?.error || 'Não foi possivel carregar o comparativo.')
        }
        if (!active) return
        setResultsData(payload)
        writeCache(resultsCacheKey, payload)
      } catch (err) {
        if (!active) return
        setResultsError(err.message || 'Não foi possivel carregar o comparativo.')
      } finally {
        if (!active) return
        setResultsLoading(false)
      }
    }

    if (quoteId) {
      loadSummary()
      loadResults()
    }
    return () => {
      active = false
    }
  }, [quoteId, summaryCacheKey, resultsCacheKey])

  const handleToggleSidebar = () => {
    const next = !collapsed
    setCollapsed(next)
    localStorage.setItem('dashboardSidebar', next ? '1' : '0')
  }

  const summaryItems = data?.items || []
  const comparisonItems = resultsData?.items || []
  const items = summaryItems.length ? summaryItems : comparisonItems
  const responses = Array.isArray(data?.responses) ? data.responses : []
  const responsesCount = responses.length || Object.keys(resultsData?.responses || {}).length
  const suppliers = resultsData?.suppliers || []
  const responsesMap = resultsData?.responses || {}
  const bestPerItem = resultsData?.best_per_item || {}

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
            <Link
              key={item.href}
              className={`dashboard-link ${isActiveLink(item.href) ? 'is-active' : ''}`}
              to={item.href}
              data-tooltip={item.label}
            >
              <i className={`fa ${item.icon}`} aria-hidden="true" />
              <span>{item.label}</span>
            </Link>
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
            <p className="dashboard-kicker">cotação</p>
            <h1>{data?.quote?.title || 'Resumo da cotação'}</h1>
            <p className="dashboard-subtitle">
              {data?.meta?.created_at || '—'} · {items.length} itens · {responsesCount} respostas
            </p>
          </div>
          <div className="dashboard-actions">
            <Link className="dashboard-icon-btn" to="/quotes" aria-label="Voltar">
              <i className="fa fa-arrow-left" aria-hidden="true" />
            </Link>
          </div>
        </header>

        {error ? <div className="dashboard-alert">{error}</div> : null}
        {loading ? <div className="dashboard-loading">Carregando resumo...</div> : null}

        {!loading ? (
          <div className="form-stack">
            <section className="dashboard-card dashboard-card--panel">
              <div className="card-title">Itens solicitados</div>
              {items.length ? (
                <div className="data-table data-table--dashboard">
                  <table>
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>Descrição</th>
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((item, index) => (
                        <tr key={`${item}-${index}`}>
                          <td>{index + 1}</td>
                          <td>{item}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="empty-state">Nenhum item cadastrado nesta cotação.</p>
              )}
            </section>

            <section className="dashboard-card dashboard-card--panel">
              <div className="card-title">Respostas dos fornecedores</div>
              {resultsLoading ? <div className="dashboard-loading">Carregando comparativo...</div> : null}
              {!resultsLoading ? (
                resultsError ? (
                  <p className="empty-state">{resultsError}</p>
                ) : (
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
                        {comparisonItems.length ? (
                          comparisonItems.map((item, idx) => (
                            <tr key={`${item}-${idx}`}>
                              <td>
                                <strong>{item}</strong>
                              </td>
                              {suppliers.map((supplier) => {
                                const answer = responsesMap?.[supplier.id]?.[idx]
                                const isBest = String(bestPerItem?.[idx]) === String(supplier.id)
                                return (
                                  <td key={`${supplier.id}-${idx}`} className={isBest ? 'quote-best' : ''}>
                                    {answer ? (
                                      <div className="quote-cell">
                                        {isBest ? <span className="quote-badge">Menor preco</span> : null}
                                        <span className="quote-price">{answer.price ? `R$ ${answer.price}` : '—'}</span>
                                        <span className="quote-deadline">
                                          {answer.deadline ? `${answer.deadline} dias` : '—'}
                                        </span>
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
                )
              ) : null}
            </section>
          </div>
        ) : null}
      </main>
    </div>
  )
}

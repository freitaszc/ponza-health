import { useEffect, useMemo, useState } from 'react'
import { Link } from '../components/Router'
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

export default function Quotes() {
  const currentPath = typeof window !== 'undefined' ? window.location.pathname : '/quotes'
  const quotesCacheKey = useMemo(() => buildCacheKey('quotes', ['all']), [])
  const initialQuotes = useMemo(() => readCache(quotesCacheKey), [quotesCacheKey])

  const [collapsed, setCollapsed] = useState(
    typeof window !== 'undefined' && localStorage.getItem('dashboardSidebar') === '1',
  )
  const [quotes, setQuotes] = useState(() => (Array.isArray(initialQuotes) ? initialQuotes : []))
  const [loading, setLoading] = useState(() => !Array.isArray(initialQuotes))
  const [error, setError] = useState('')
  const [deletingId, setDeletingId] = useState(null)
  const [searchInput, setSearchInput] = useState('')
  const [statusFilter, setStatusFilter] = useState(['responded', 'pending'])

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
    const cached = readCache(quotesCacheKey)
    if (cached && Array.isArray(cached)) {
      setQuotes(cached)
      setLoading(false)
    } else {
      setLoading(true)
    }
    const load = async () => {
      setError('')
      try {
        const response = await fetch('/api/quotes', { credentials: 'include' })
        const payload = await response.json().catch(() => ({}))
        if (!response.ok || payload?.success === false) {
          throw new Error(payload?.error || 'Não foi possivel carregar as cotações.')
        }
        if (!active) return
        const nextQuotes = payload?.quotes || []
        setQuotes(nextQuotes)
        writeCache(quotesCacheKey, nextQuotes)
      } catch (err) {
        if (!active) return
        setError(err.message || 'Não foi possivel carregar as cotações.')
      } finally {
        if (!active) return
        setLoading(false)
      }
    }
    load()
    return () => {
      active = false
    }
  }, [quotesCacheKey])

  const handleToggleSidebar = () => {
    const next = !collapsed
    setCollapsed(next)
    localStorage.setItem('dashboardSidebar', next ? '1' : '0')
  }

  const handleDelete = async (quoteId) => {
    if (!quoteId) return
    if (!window.confirm('Deseja remover esta cotação?')) return
    setDeletingId(quoteId)
    try {
      const response = await fetch(`/quotes/${quoteId}/delete`, {
        method: 'POST',
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          Accept: 'application/json',
        },
        credentials: 'include',
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok || payload?.success === false) {
        throw new Error(payload?.message || 'Não foi possivel remover a cotação.')
      }
      setQuotes((prev) => {
        const nextQuotes = prev.filter((item) => item.id !== quoteId)
        writeCache(quotesCacheKey, nextQuotes)
        return nextQuotes
      })
    } catch (err) {
      setError(err.message || 'Não foi possivel remover a cotação.')
    } finally {
      setDeletingId(null)
    }
  }

  const statusCounts = useMemo(() => {
    const responded = quotes.filter((quote) => (quote.responses_count ?? 0) > 0).length
    return {
      all: quotes.length,
      responded,
      pending: quotes.length - responded,
    }
  }, [quotes])

  const filteredQuotes = useMemo(() => {
    const normalizedSearch = searchInput.trim().toLowerCase()
    return quotes.filter((quote) => {
      const responsesCount = Number(quote.responses_count || 0)
      const statusKey = responsesCount > 0 ? 'responded' : 'pending'
      const matchesStatus = statusFilter.includes(statusKey)
      if (!normalizedSearch) {
        return matchesStatus
      }
      const titleMatch = quote.title?.toLowerCase().includes(normalizedSearch)
      const supplierMatch = quote.suppliers?.some((supplier) =>
        supplier?.name?.toLowerCase().includes(normalizedSearch),
      )
      return matchesStatus && (titleMatch || supplierMatch)
    })
  }, [quotes, searchInput, statusFilter])

  const handleStatusFilter = (nextStatus) => {
    setStatusFilter((prev) => {
      const next = prev.includes(nextStatus) ? prev.filter((value) => value !== nextStatus) : [...prev, nextStatus]
      if (!next.length) {
        return ['responded', 'pending']
      }
      return ['responded', 'pending'].filter((value) => next.includes(value))
    })
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
          {sidebarNav.map((item) => (
            <Link
              key={item.href}
              className={`dashboard-link ${isActiveLink(item.href) ? 'is-active' : ''}`}
              to={item.href}
            >
              <i className={`fa ${item.icon}`} aria-hidden="true" />
              <span>{item.label}</span>
            </Link>
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
            <p className="dashboard-kicker">Cotações</p>
            <h1>Cotações e fornecedores</h1>
            <p className="dashboard-subtitle">Acompanhe todas as solicitações enviadas.</p>
          </div>
          <div className="dashboard-actions">
            <Link className="dashboard-icon-btn" to="/account" aria-label="Minha conta">
              <i className="fa fa-user" aria-hidden="true" />
            </Link>
            <button className="dashboard-icon-btn" type="button" aria-label="Notificações">
              <i className="fa fa-bell" aria-hidden="true" />
            </button>
          </div>
        </header>

        {error ? <div className="dashboard-alert">{error}</div> : null}
        {loading ? <div className="dashboard-loading">Carregando cotações...</div> : null}

        {!loading ? (
          <div className="data-table data-table--spaced data-table--controls data-table--dashboard">
            <div className="data-table__head">
              <div className="data-table__tools">
                <label className="data-table__search">
                  <i className="fa fa-search" aria-hidden="true" />
                  <input
                    type="search"
                    placeholder="Buscar cotação"
                    value={searchInput}
                    onChange={(event) => setSearchInput(event.target.value)}
                  />
                </label>
                <div className="data-table__filters" role="group" aria-label="Status da cotação">
                  {[
                    { label: 'Respondidas', value: 'responded', count: statusCounts.responded },
                    { label: 'Pendentes', value: 'pending', count: statusCounts.pending },
                  ].map((status) => (
                    <button
                      key={status.label}
                      type="button"
                      className={`filter-chip ${statusFilter.includes(status.value) ? 'is-active' : ''}`}
                      onClick={() => handleStatusFilter(status.value)}
                    >
                      {status.label}
                      <span className="filter-chip__count">{status.count}</span>
                    </button>
                  ))}
                </div>
              </div>
              <div className="data-table__aside">
                <Link className="btn-primary" to="/quotes/create">Nova cotação</Link>
                <Link className="btn-outline" to="/suppliers">Gerenciar fornecedores</Link>
              </div>
            </div>
            <table className="quotes-table">
              <thead>
                <tr>
                  <th>Nome</th>
                  <th>Criada em</th>
                  <th>Fornecedores</th>
                  <th>Respostas</th>
                  <th>ações</th>
                </tr>
              </thead>
              <tbody>
                {filteredQuotes.length ? (
                  filteredQuotes.map((quote) => (
                    <tr key={quote.id}>
                      <td>
                        <Link className="text-link" to={`/quotes/${quote.id}`}>
                          {quote.title}
                        </Link>
                      </td>
                      <td>{quote.created_at_br || '—'}</td>
                      <td>
                        {(() => {
                          const suppliersCount = quote.suppliers?.length || 0
                          if (!suppliersCount) return '—'
                          return `${suppliersCount} fornecedor${suppliersCount === 1 ? '' : 'es'}`
                        })()}
                      </td>
                      <td>{quote.responses_count ?? 0}</td>
                      <td>
                        <div className="table-actions">
                          <Link className="icon-button" to={`/quotes/${quote.id}`} aria-label="Ver informações">
                            <i className="fa fa-info-circle" aria-hidden="true" />
                          </Link>
                          <button
                            type="button"
                            className="icon-button is-danger"
                            onClick={() => handleDelete(quote.id)}
                            disabled={deletingId === quote.id}
                            aria-label="Excluir cotação"
                          >
                            <i className="fa fa-trash-o" aria-hidden="true" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan="5" className="empty-cell">
                      Nenhuma cotação encontrada.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        ) : null}
      </main>
    </div>
  )
}

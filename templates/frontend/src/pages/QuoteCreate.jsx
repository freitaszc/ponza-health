import { useEffect, useMemo, useState } from 'react'

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

export default function QuoteCreate() {
  const currentPath = typeof window !== 'undefined' ? window.location.pathname : '/quotes/create'
  const [collapsed, setCollapsed] = useState(
    typeof window !== 'undefined' && localStorage.getItem('dashboardSidebar') === '1',
  )
  const [title, setTitle] = useState('')
  const [items, setItems] = useState('')
  const [suppliers, setSuppliers] = useState([])
  const [selectedSuppliers, setSelectedSuppliers] = useState([])
  const [loadingSuppliers, setLoadingSuppliers] = useState(true)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

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
      setLoadingSuppliers(true)
      try {
        const response = await fetch('/api/suppliers', { credentials: 'include' })
        const payload = await response.json().catch(() => [])
        if (!response.ok) {
          throw new Error('Não foi possivel carregar fornecedores.')
        }
        if (!active) return
        setSuppliers(Array.isArray(payload) ? payload : [])
      } catch (err) {
        if (!active) return
        setError(err.message || 'Não foi possivel carregar fornecedores.')
      } finally {
        if (!active) return
        setLoadingSuppliers(false)
      }
    }
    load()
    return () => {
      active = false
    }
  }, [])

  const handleToggleSidebar = () => {
    const next = !collapsed
    setCollapsed(next)
    localStorage.setItem('dashboardSidebar', next ? '1' : '0')
  }

  const toggleSupplier = (id) => {
    setSelectedSuppliers((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id],
    )
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    setError('')

    const itemsList = items
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)

    if (!title.trim()) {
      setError('Informe o nome da cotação.')
      return
    }
    if (!itemsList.length) {
      setError('Adicione ao menos um item.')
      return
    }

    setSubmitting(true)
    try {
      const response = await fetch('/api/quotes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: title.trim(),
          items: itemsList,
          supplier_ids: selectedSuppliers,
        }),
        credentials: 'include',
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok || payload?.success === false) {
        throw new Error(payload?.error || 'Não foi possivel criar a cotação.')
      }
      const redirect = payload?.redirect_url || '/quotes'
      window.location.href = redirect
    } catch (err) {
      setError(err.message || 'Não foi possivel criar a cotação.')
    } finally {
      setSubmitting(false)
    }
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
            <p className="dashboard-kicker">Cotações</p>
            <h1>Criar nova cotação</h1>
            <p className="dashboard-subtitle">Envie a lista de itens e selecione os fornecedores.</p>
          </div>
          <div className="dashboard-actions">
            <a className="dashboard-icon-btn" href="/quotes" aria-label="Voltar">
              <i className="fa fa-arrow-left" aria-hidden="true" />
            </a>
          </div>
        </header>

        {error ? <div className="dashboard-alert">{error}</div> : null}

        <form className="form-stack" onSubmit={handleSubmit}>
          <section className="dashboard-card dashboard-card--panel">
            <div className="card-title">Informações gerais</div>
            <div className="form-grid form-grid--2">
              <label className="dashboard-field">
                <span>Nome da cotação *</span>
                <input
                  className="dashboard-input"
                  placeholder="Ex: Reposicao de estoque"
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  required
                />
              </label>
            </div>
            <label className="dashboard-field">
              <span>Itens *</span>
              <textarea
                className="dashboard-textarea"
                rows="6"
                placeholder="Um item por linha"
                value={items}
                onChange={(event) => setItems(event.target.value)}
                required
              />
            </label>
          </section>

          <section className="dashboard-card dashboard-card--panel">
            <div className="card-title">Fornecedores</div>
            {loadingSuppliers ? <p className="dashboard-loading">Carregando fornecedores...</p> : null}
            {!loadingSuppliers && suppliers.length ? (
              <div className="supplier-grid">
                {suppliers.map((supplier) => (
                  <label key={supplier.id} className="supplier-card">
                    <input
                      type="checkbox"
                      checked={selectedSuppliers.includes(supplier.id)}
                      onChange={() => toggleSupplier(supplier.id)}
                    />
                    <div>
                      <strong>{supplier.name}</strong>
                      <span>{supplier.phone || supplier.email || 'Sem contato'}</span>
                    </div>
                  </label>
                ))}
              </div>
            ) : null}
            {!loadingSuppliers && !suppliers.length ? (
              <p className="empty-state">Nenhum fornecedor cadastrado. Cadastre em Fornecedores.</p>
            ) : null}
          </section>

          <div className="form-actions">
            <a className="btn-outline" href="/quotes">Cancelar</a>
            <button type="submit" className="btn-primary" disabled={submitting}>
              {submitting ? 'Criando...' : 'Criar cotação'}
            </button>
          </div>
        </form>

        {submitting ? (
          <div className="quote-overlay" aria-live="polite">
            <div className="quote-overlay__card">
              <img src="/static/images/6.svg" alt="Ponza Health" />
              <h3>Criando sua cotação</h3>
              <p>Estamos gerando o PDF e avisando os fornecedores selecionados.</p>
              <div className="loading-dots">
                <span />
                <span />
                <span />
              </div>
            </div>
          </div>
        ) : null}
      </main>
    </div>
  )
}

import { useEffect, useMemo, useState } from 'react'
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

const emptySupplier = {
  name: '',
  email: '',
  phone: '',
}

export default function Suppliers() {
  const currentPath = typeof window !== 'undefined' ? window.location.pathname : '/suppliers'
  const [collapsed, setCollapsed] = useState(
    typeof window !== 'undefined' && localStorage.getItem('dashboardSidebar') === '1',
  )
  const [suppliers, setSuppliers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [modalMode, setModalMode] = useState('add')
  const [modalSupplierId, setModalSupplierId] = useState(null)
  const [formValues, setFormValues] = useState(emptySupplier)
  const [modalError, setModalError] = useState('')
  const [modalSubmitting, setModalSubmitting] = useState(false)
  const [busySupplierId, setBusySupplierId] = useState(null)

  const suppliersCacheKey = useMemo(() => buildCacheKey('suppliers', ['all']), [])

  const sidebarNav = useMemo(() => navItems, [])
  const isActiveLink = (href) => {
    const resolved = resolvePath(href)
    if (resolved === '/quotes') {
      return currentPath.startsWith('/quotes') || currentPath.startsWith('/suppliers')
    }
    if (resolved === '/catalog') {
      return (
        currentPath.startsWith('/catalog') ||
        currentPath.startsWith('/edit_patient') ||
        currentPath.startsWith('/patient_info')
      )
    }
    if (resolved === '/products') {
      return currentPath.startsWith('/products')
    }
    return currentPath === resolved
  }

  useEffect(() => {
    let active = true
    const cached = readCache(suppliersCacheKey)
    if (cached && Array.isArray(cached)) {
      setSuppliers(cached)
      setLoading(false)
    } else {
      setLoading(true)
    }
    const load = async () => {
      setError('')
      try {
        const response = await fetch('/api/suppliers', { credentials: 'include' })
        const payload = await response.json().catch(() => [])
        if (!response.ok) {
          throw new Error('Nao foi possivel carregar fornecedores.')
        }
        if (!active) return
        const nextSuppliers = Array.isArray(payload) ? payload : []
        setSuppliers(nextSuppliers)
        writeCache(suppliersCacheKey, nextSuppliers)
      } catch (err) {
        if (!active) return
        setError(err.message || 'Nao foi possivel carregar fornecedores.')
      } finally {
        if (!active) return
        setLoading(false)
      }
    }
    load()
    return () => {
      active = false
    }
  }, [])

  const filteredSuppliers = useMemo(() => {
    const search = searchInput.trim().toLowerCase()
    if (!search) return suppliers
    return suppliers.filter((supplier) =>
      [supplier.name, supplier.email, supplier.phone].some((value) =>
        (value || '').toLowerCase().includes(search),
      ),
    )
  }, [suppliers, searchInput])

  const handleToggleSidebar = () => {
    const next = !collapsed
    setCollapsed(next)
    localStorage.setItem('dashboardSidebar', next ? '1' : '0')
  }

  const openAddModal = () => {
    setModalMode('add')
    setModalSupplierId(null)
    setFormValues(emptySupplier)
    setModalError('')
    setModalOpen(true)
  }

  const openEditModal = (supplier) => {
    setModalMode('edit')
    setModalSupplierId(supplier?.id || null)
    setFormValues({
      name: supplier?.name || '',
      email: supplier?.email || '',
      phone: supplier?.phone || '',
    })
    setModalError('')
    setModalOpen(true)
  }

  const closeModal = () => {
    if (modalSubmitting) return
    setModalOpen(false)
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    setModalError('')
    const name = formValues.name.trim()
    if (!name) {
      setModalError('Informe o nome do fornecedor.')
      return
    }
    setModalSubmitting(true)
    try {
      let response
      if (modalMode === 'edit' && modalSupplierId) {
        response = await fetch(`/update_supplier/${modalSupplierId}`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
            Accept: 'application/json',
          },
          credentials: 'include',
          body: JSON.stringify({
            name,
            email: formValues.email.trim(),
            phone: formValues.phone.trim(),
          }),
        })
      } else {
        response = await fetch('/api/suppliers', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            name,
            email: formValues.email.trim(),
            phone: formValues.phone.trim(),
          }),
        })
      }

      const payload = await response.json().catch(() => ({}))
      if (!response.ok || payload?.success === false) {
        throw new Error(payload?.error || 'Nao foi possivel salvar o fornecedor.')
      }

      setModalOpen(false)
      setFormValues(emptySupplier)

      const refreshed = await fetch('/api/suppliers', { credentials: 'include' })
      const refreshedPayload = await refreshed.json().catch(() => [])
      const nextSuppliers = Array.isArray(refreshedPayload) ? refreshedPayload : []
      setSuppliers(nextSuppliers)
      writeCache(suppliersCacheKey, nextSuppliers)
    } catch (err) {
      setModalError(err.message || 'Nao foi possivel salvar o fornecedor.')
    } finally {
      setModalSubmitting(false)
    }
  }

  const handleDelete = async (supplierId) => {
    if (!supplierId) return
    if (!window.confirm('Deseja realmente excluir este fornecedor?')) return
    setBusySupplierId(supplierId)
    try {
      const response = await fetch(`/suppliers/${supplierId}/delete`, {
        method: 'POST',
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          Accept: 'application/json',
        },
        credentials: 'include',
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok || payload?.success === false) {
        throw new Error(payload?.error || 'Nao foi possivel excluir o fornecedor.')
      }
      setSuppliers((prev) => {
        const nextSuppliers = prev.filter((item) => item.id !== supplierId)
        writeCache(suppliersCacheKey, nextSuppliers)
        return nextSuppliers
      })
    } catch (err) {
      setError(err.message || 'Nao foi possivel excluir o fornecedor.')
    } finally {
      setBusySupplierId(null)
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
            <p className="dashboard-kicker">Fornecedores</p>
            <h1>Rede de fornecedores</h1>
            <div className="dashboard-chips">
              <span>{filteredSuppliers.length} fornecedores encontrados</span>
            </div>
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

        {error ? <div className="dashboard-alert">{error}</div> : null}
        {loading ? <div className="dashboard-loading">Carregando fornecedores...</div> : null}

        {!loading ? (
          <div className="data-table data-table--spaced data-table--dashboard">
            <div className="data-table__head">
              <div className="data-table__tools">
                <label className="data-table__search">
                  <i className="fa fa-search" aria-hidden="true" />
                  <input
                    type="search"
                    placeholder="Buscar fornecedor"
                    value={searchInput}
                    onChange={(event) => setSearchInput(event.target.value)}
                  />
                </label>
              </div>
              <div className="data-table__aside">
                <button className="btn-primary" type="button" onClick={openAddModal}>
                  Novo fornecedor
                </button>
              </div>
            </div>
            <table>
              <thead>
                <tr>
                  <th>Fornecedor</th>
                  <th>Email</th>
                  <th>Telefone</th>
                  <th>Ações</th>
                </tr>
              </thead>
              <tbody>
                {filteredSuppliers.length ? (
                  filteredSuppliers.map((supplier) => (
                    <tr key={supplier.id}>
                      <td>{supplier.name}</td>
                      <td>{supplier.email || '—'}</td>
                      <td>{supplier.phone || '—'}</td>
                      <td>
                        <div className="table-actions">
                          <button
                            type="button"
                            className="icon-button"
                            aria-label="Editar fornecedor"
                            onClick={() => openEditModal(supplier)}
                          >
                            <i className="fa fa-pencil" aria-hidden="true" />
                          </button>
                          <button
                            type="button"
                            className="icon-button is-danger"
                            aria-label="Excluir fornecedor"
                            onClick={() => handleDelete(supplier.id)}
                            disabled={busySupplierId === supplier.id}
                          >
                            <i className="fa fa-trash" aria-hidden="true" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan="4" className="empty-cell">
                      Nenhum fornecedor encontrado.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        ) : null}
      </main>

      {modalOpen ? (
        <div
          className="dashboard-modal"
          role="dialog"
          aria-modal="true"
          onClick={(event) => {
            if (event.target === event.currentTarget) closeModal()
          }}
        >
          <div className="dashboard-modal__card">
            <div className="dashboard-modal__header">
              <div>
                <p className="dashboard-kicker">
                  {modalMode === 'edit' ? 'Editar fornecedor' : 'Novo fornecedor'}
                </p>
                <h3>{modalMode === 'edit' ? 'Atualizar dados' : 'Cadastrar fornecedor'}</h3>
              </div>
              <button className="icon-button" type="button" onClick={closeModal} aria-label="Fechar">
                <i className="fa fa-times" aria-hidden="true" />
              </button>
            </div>

            {modalError ? <div className="dashboard-alert">{modalError}</div> : null}

            <form className="dashboard-modal__body" onSubmit={handleSubmit}>
              <label className="dashboard-field">
                <span>Nome</span>
                <input
                  className="dashboard-input"
                  value={formValues.name}
                  onChange={(event) => setFormValues((prev) => ({ ...prev, name: event.target.value }))}
                  placeholder="Nome do fornecedor"
                />
              </label>
              <label className="dashboard-field">
                <span>Email</span>
                <input
                  className="dashboard-input"
                  type="email"
                  value={formValues.email}
                  onChange={(event) => setFormValues((prev) => ({ ...prev, email: event.target.value }))}
                  placeholder="email@fornecedor.com"
                />
              </label>
              <label className="dashboard-field">
                <span>Telefone</span>
                <input
                  className="dashboard-input"
                  value={formValues.phone}
                  onChange={(event) => setFormValues((prev) => ({ ...prev, phone: event.target.value }))}
                  placeholder="(00) 00000-0000"
                />
              </label>
              <div className="dashboard-modal__actions">
                <button type="submit" className="btn-primary" disabled={modalSubmitting}>
                  {modalSubmitting ? 'Salvando...' : 'Salvar fornecedor'}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </div>
  )
}

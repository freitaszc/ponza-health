import { useCallback, useEffect, useMemo, useState } from 'react'
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

const productStatusFilters = [
  { label: 'Ativos', value: 'Ativo' },
  { label: 'Inativos', value: 'Inativo' },
]

const getInitialFilters = () => {
  if (typeof window === 'undefined') {
    return { search: '', status: productStatusFilters.map((status) => status.value) }
  }
  const params = new URLSearchParams(window.location.search)
  const statusParam = params.get('status') || ''
  const statusSelection = productStatusFilters.some((status) => status.value === statusParam)
    ? [statusParam]
    : productStatusFilters.map((status) => status.value)
  return {
    search: params.get('search') || '',
    status: statusSelection,
  }
}

const formatCurrency = (value) => {
  const amount = Number(value)
  if (Number.isNaN(amount)) return 'R$ 0,00'
  return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(amount)
}

const formatNumber = (value) => new Intl.NumberFormat('pt-BR').format(value || 0)

const emptyProduct = {
  name: '',
  quantity: '',
  purchase_price: '',
  sale_price: '',
}

export default function Stock() {
  const [products, setProducts] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [filters, setFilters] = useState(() => getInitialFilters())
  const [appliedFilters, setAppliedFilters] = useState(() => getInitialFilters())
  const [isAdmin, setIsAdmin] = useState(false)
  const [notificationsUnread, setNotificationsUnread] = useState(0)
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('dashboardSidebar') === '1')
  const [busyIds, setBusyIds] = useState({})
  const [showAddModal, setShowAddModal] = useState(false)
  const [addForm, setAddForm] = useState(emptyProduct)
  const [addError, setAddError] = useState('')
  const [addSubmitting, setAddSubmitting] = useState(false)
  const [showMovementModal, setShowMovementModal] = useState(false)
  const [movementError, setMovementError] = useState('')
  const [movementSubmitting, setMovementSubmitting] = useState(false)
  const [movement, setMovement] = useState({ productId: null, type: 'in', quantity: '', notes: '' })
  const [showHistoryModal, setShowHistoryModal] = useState(false)
  const [historyRecords, setHistoryRecords] = useState([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState('')

  const currentPath = typeof window !== 'undefined' ? window.location.pathname : '/products'
  const sidebarNav = useMemo(() => {
    if (isAdmin) {
      return [...navItems, { label: 'Admin', href: withBackend('/admin_users'), icon: 'fa-shield' }]
    }
    return navItems
  }, [isAdmin])
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
    if (resolved === '/products') {
      return currentPath.startsWith('/products')
    }
    return currentPath === resolved
  }

  const handleToggleSidebar = () => {
    const next = !collapsed
    setCollapsed(next)
    localStorage.setItem('dashboardSidebar', next ? '1' : '0')
  }

  const loadProducts = useCallback(async (nextFilters) => {
    const statusKey = nextFilters.status.length === 1 ? nextFilters.status[0] : 'all'
    const cacheKey = buildCacheKey('stock', [nextFilters.search || 'all', statusKey])
    const cached = readCache(cacheKey)
    if (cached && Array.isArray(cached.products)) {
      setProducts(cached.products)
      setIsAdmin(Boolean(cached.is_admin))
      setNotificationsUnread(cached.notifications_unread || 0)
      setLoading(false)
    } else {
      setLoading(true)
    }
    setError('')
    try {
      const params = new URLSearchParams()
      if (nextFilters.search) params.set('search', nextFilters.search)
      if (nextFilters.status.length === 1) params.set('status', nextFilters.status[0])
      const url = params.toString() ? `/api/products?${params}` : '/api/products'
      const response = await fetch(url, { credentials: 'same-origin' })
      if (!response.ok) {
        throw new Error('Erro ao carregar')
      }
      const data = await response.json()
      const nextProducts = Array.isArray(data.products) ? data.products : []
      setProducts(nextProducts)
      setIsAdmin(Boolean(data.is_admin))
      setNotificationsUnread(data.notifications_unread || 0)
      writeCache(cacheKey, {
        products: nextProducts,
        is_admin: Boolean(data.is_admin),
        notifications_unread: data.notifications_unread || 0,
      })
    } catch (err) {
      setError('Não foi possível carregar o estoque.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadProducts(appliedFilters)
  }, [appliedFilters, loadProducts])

  useEffect(() => {
    if (typeof window === 'undefined') return
    const params = new URLSearchParams()
    if (appliedFilters.search) params.set('search', appliedFilters.search)
    if (appliedFilters.status.length === 1) params.set('status', appliedFilters.status[0])
    const nextUrl = params.toString() ? `${window.location.pathname}?${params}` : window.location.pathname
    window.history.replaceState({}, '', nextUrl)
  }, [appliedFilters])

  useEffect(() => {
    if (!showAddModal && !showMovementModal && !showHistoryModal) return
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        setShowAddModal(false)
        setShowMovementModal(false)
        setShowHistoryModal(false)
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [showAddModal, showMovementModal, showHistoryModal])

  useEffect(() => {
    if (!showHistoryModal) return
    let active = true
    setHistoryLoading(true)
    setHistoryError('')
    fetch('/api/stock_history', { credentials: 'same-origin' })
      .then((response) => {
        if (!response.ok) {
          throw new Error('Erro ao carregar')
        }
        return response.json()
      })
      .then((data) => {
        if (!active) return
        if (!data.success) {
          setHistoryError('Não foi possível carregar o histórico.')
          setHistoryRecords([])
          return
        }
        setHistoryRecords(Array.isArray(data.records) ? data.records : [])
      })
      .catch(() => {
        if (!active) return
        setHistoryError('Não foi possível carregar o histórico.')
        setHistoryRecords([])
      })
      .finally(() => {
        if (!active) return
        setHistoryLoading(false)
      })
    return () => {
      active = false
    }
  }, [showHistoryModal])

  const handleStatusFilter = (nextStatus) => {
    const nextSelection = filters.status.includes(nextStatus)
      ? filters.status.filter((status) => status !== nextStatus)
      : [...filters.status, nextStatus]
    const normalizedSelection = nextSelection.length
      ? productStatusFilters.map((status) => status.value).filter((value) => nextSelection.includes(value))
      : productStatusFilters.map((status) => status.value)
    const nextFilters = { ...filters, status: normalizedSelection }
    setFilters(nextFilters)
    setAppliedFilters(nextFilters)
  }

  useEffect(() => {
    const timeout = setTimeout(() => {
      setAppliedFilters((prev) => {
        const next = { ...prev, search: filters.search, status: filters.status }
        if (prev.search === next.search && prev.status.join('|') === next.status.join('|')) {
          return prev
        }
        return next
      })
    }, 250)
    return () => clearTimeout(timeout)
  }, [filters.search, filters.status])

  const statusCounts = useMemo(() => {
    const activeCount = products.filter((product) => product.status === 'Ativo').length
    return {
      all: products.length,
      active: activeCount,
      inactive: products.length - activeCount,
    }
  }, [products])

  const handleOpenAddModal = () => {
    setAddForm(emptyProduct)
    setAddError('')
    setShowAddModal(true)
  }

  const handleAddSubmit = async (event) => {
    event.preventDefault()
    setAddError('')
    const name = addForm.name.trim()
    if (!name) {
      setAddError('Informe o nome do produto.')
      return
    }
    setAddSubmitting(true)
    try {
      const payload = {
        name,
        quantity: Number(addForm.quantity) || 0,
        purchase_price: addForm.purchase_price,
        sale_price: addForm.sale_price,
      }
      const response = await fetch('/api/products', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify(payload),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Erro ao cadastrar')
      }
      setShowAddModal(false)
      setAddForm(emptyProduct)
      await loadProducts(appliedFilters)
    } catch (err) {
      setAddError(err.message || 'Não foi possível salvar o produto.')
    } finally {
      setAddSubmitting(false)
    }
  }

  const openMovementModal = (productId, type) => {
    setMovement({ productId, type, quantity: '', notes: '' })
    setMovementError('')
    setShowMovementModal(true)
  }

  const handleMovementSubmit = async (event) => {
    event.preventDefault()
    setMovementError('')
    const qty = parseInt(movement.quantity, 10)
    if (!qty || qty <= 0) {
      setMovementError('Informe a quantidade.')
      return
    }
    setMovementSubmitting(true)
    try {
      const payload = {
        product_id: movement.productId,
        quantity: qty,
        notes: movement.notes,
        type: movement.type,
      }
      const response = await fetch('/api/stock_movement', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify(payload),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Não foi possível registrar a movimentação.')
      }
      setProducts((prev) =>
        prev.map((item) =>
          item.id === data.product_id ? { ...item, quantity: data.quantity } : item,
        ),
      )
      setShowMovementModal(false)
    } catch (err) {
      setMovementError(err.message || 'Não foi possível registrar a movimentação.')
    } finally {
      setMovementSubmitting(false)
    }
  }

  const handleToggleStatus = async (product) => {
    const nextStatus = product.status === 'Ativo' ? 'Inativo' : 'Ativo'
    setBusyIds((prev) => ({ ...prev, [product.id]: true }))
    try {
      const response = await fetch(`/products/${product.id}/toggle-status`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
          Accept: 'application/json',
        },
        credentials: 'same-origin',
        body: JSON.stringify({ new_status: nextStatus }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok || !data.success) {
        throw new Error('Erro ao atualizar')
      }
      setProducts((prev) =>
        prev.map((item) =>
          item.id === product.id ? { ...item, status: data.status || nextStatus } : item,
        ),
      )
    } catch (err) {
      window.alert('Não foi possível atualizar o status. Tente novamente.')
    } finally {
      setBusyIds((prev) => ({ ...prev, [product.id]: false }))
    }
  }

  const handleDeleteProduct = async (productId) => {
    if (!window.confirm('Deseja realmente remover este produto?')) return
    setBusyIds((prev) => ({ ...prev, [productId]: true }))
    try {
      const response = await fetch(`/delete_product/${productId}`, {
        method: 'POST',
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          Accept: 'application/json',
        },
        credentials: 'same-origin',
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok || !data.success) {
        throw new Error('Erro ao remover')
      }
      setProducts((prev) => prev.filter((item) => item.id !== productId))
    } catch (err) {
      window.alert('Não foi possível remover o produto. Tente novamente.')
    } finally {
      setBusyIds((prev) => ({ ...prev, [productId]: false }))
    }
  }

  return (
    <div className={`dashboard-shell stock-shell ${collapsed ? 'is-collapsed' : ''}`}>
      <aside className="dashboard-sidebar">
        <div className="dashboard-sidebar__brand">
          
          <div className="dashboard-logo-wrap">
            <img src="/static/images/5.svg" alt="Ponza Health" className="dashboard-logo dashboard-logo--full" />
            <img src="/static/images/15.svg" alt="Ponza Health" className="dashboard-logo dashboard-logo--compact" />
          </div>
          <div className="dashboard-title"></div>
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
            <p className="dashboard-kicker">Estoque</p>
            <h1>Controle seus produtos e movimentações</h1>
          </div>
          <div className="dashboard-actions">
            <a className="dashboard-icon-btn" href="/account" aria-label="Minha conta">
              <i className="fa fa-user" aria-hidden="true" />
            </a>
            <button className="dashboard-icon-btn" type="button" aria-label="Notificações">
              <i className="fa fa-bell" aria-hidden="true" />
              {notificationsUnread ? <span className="badge">{notificationsUnread}</span> : null}
            </button>
          </div>
        </header>

        {error ? <div className="dashboard-alert">{error}</div> : null}

        <div className="data-table data-table--spaced data-table--controls data-table--dashboard stock-table">
          <div className="data-table__head">
            <div className="data-table__tools">
              <label className="data-table__search">
                <i className="fa fa-search" aria-hidden="true" />
                <input
                  type="search"
                  placeholder="Pesquisar produto..."
                  value={filters.search}
                  onChange={(event) => setFilters((prev) => ({ ...prev, search: event.target.value }))}
                />
              </label>
              <div className="data-table__filters" role="group" aria-label="Status do produto">
                {[
                  { label: 'Ativos', value: 'Ativo', count: statusCounts.active },
                  { label: 'Inativos', value: 'Inativo', count: statusCounts.inactive },
                ].map((status) => (
                  <button
                    key={status.label}
                    type="button"
                    className={`filter-chip ${filters.status.includes(status.value) ? 'is-active' : ''}`}
                    onClick={() => handleStatusFilter(status.value)}
                  >
                    {status.label}
                    <span className="filter-chip__count">{status.count}</span>
                  </button>
                ))}
              </div>
            </div>
            <div className="data-table__aside">
              <button className="btn-primary" type="button" onClick={handleOpenAddModal}>
                Cadastrar produto
              </button>
              <button className="btn-outline" type="button" onClick={() => setShowHistoryModal(true)}>
                Movimentações (últimos 30 dias)
              </button>
            </div>
          </div>
          <table>
            <thead>
              <tr>
                <th>Produto</th>
                <th>Quantidade</th>
                <th>Compra</th>
                <th>Venda</th>
                <th>Status</th>
                <th className="stock-actions-head">Ações</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan="6" className="stock-empty">
                    Carregando...
                  </td>
                </tr>
              ) : products.length ? (
                products.map((product) => (
                  <tr key={product.id}>
                    <td>{product.name}</td>
                    <td>{formatNumber(product.quantity)}</td>
                    <td>{formatCurrency(product.purchase_price)}</td>
                    <td>{formatCurrency(product.sale_price)}</td>
                    <td>
                      <button
                        type="button"
                        className={`status-pill status-toggle ${product.status === 'Ativo' ? 'status-pill--success' : 'status-pill--muted'}`}
                        onClick={() => handleToggleStatus(product)}
                        disabled={busyIds[product.id]}
                      >
                        {product.status || 'Inativo'}
                      </button>
                    </td>
                    <td>
                      <div className="stock-actions-cell">
                        <button
                          className="icon-button is-in"
                          type="button"
                          title="Entrada de estoque"
                          aria-label="Entrada de estoque"
                          onClick={() => openMovementModal(product.id, 'in')}
                          disabled={busyIds[product.id]}
                        >
                          <i className="fa fa-arrow-down" aria-hidden="true" />
                        </button>
                        <button
                          className="icon-button is-out"
                          type="button"
                          title="Saída de estoque"
                          aria-label="Saída de estoque"
                          onClick={() => openMovementModal(product.id, 'out')}
                          disabled={busyIds[product.id]}
                        >
                          <i className="fa fa-arrow-up" aria-hidden="true" />
                        </button>
                        <button
                          className="icon-button is-danger"
                          type="button"
                          title="Remover produto"
                          aria-label="Remover produto"
                          onClick={() => handleDeleteProduct(product.id)}
                          disabled={busyIds[product.id]}
                        >
                          <i className="fa fa-trash" aria-hidden="true" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan="6" className="stock-empty">
                    Nenhum produto encontrado.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </main>

      {showAddModal ? (
        <div
          className="dashboard-modal"
          role="dialog"
          aria-modal="true"
          aria-label="Cadastrar produto"
          onClick={(event) => {
            if (event.target === event.currentTarget) {
              setShowAddModal(false)
            }
          }}
        >
          <div
            className="dashboard-modal__card dashboard-modal__card--wide dashboard-modal__card--stock"
            style={{ width: '900px', maxWidth: '100%' }}
          >
            <div className="dashboard-modal__header">
              <div>
                <p className="dashboard-kicker">Estoque</p>
                <h3>Cadastrar produto</h3>
                <p className="dashboard-subtitle">Cadastre novos itens para atualizar o controle do estoque.</p>
              </div>
              <button className="icon-button" type="button" onClick={() => setShowAddModal(false)} aria-label="Fechar">
                <i className="fa fa-times" aria-hidden="true" />
              </button>
            </div>
            <form className="dashboard-form" onSubmit={handleAddSubmit}>
              <label>
                Produto
                <input
                  type="text"
                  value={addForm.name}
                  onChange={(event) => setAddForm((prev) => ({ ...prev, name: event.target.value }))}
                  placeholder="Nome do produto"
                  required
                />
              </label>
              <label>
                Quantidade
                <input
                  type="number"
                  min="0"
                  value={addForm.quantity}
                  onChange={(event) => setAddForm((prev) => ({ ...prev, quantity: event.target.value }))}
                  placeholder="Quantidade"
                />
              </label>
              <label>
                Preço de compra
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={addForm.purchase_price}
                  onChange={(event) => setAddForm((prev) => ({ ...prev, purchase_price: event.target.value }))}
                  placeholder="R$ 0,00"
                />
              </label>
              <label>
                Preço de venda
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={addForm.sale_price}
                  onChange={(event) => setAddForm((prev) => ({ ...prev, sale_price: event.target.value }))}
                  placeholder="R$ 0,00"
                />
              </label>
              {addError ? <div className="dashboard-form__error">{addError}</div> : null}
              <div className="dashboard-form__actions">
                <button className="btn-outline" type="button" onClick={() => setShowAddModal(false)}>
                  Cancelar
                </button>
                <button className="btn-primary" type="submit" disabled={addSubmitting}>
                  {addSubmitting ? 'Salvando...' : 'Salvar'}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}

      {showMovementModal ? (
        <div
          className="dashboard-modal"
          role="dialog"
          aria-modal="true"
          aria-label="Movimentação de estoque"
          onClick={(event) => {
            if (event.target === event.currentTarget) {
              setShowMovementModal(false)
            }
          }}
        >
          <div className="dashboard-modal__card dashboard-modal__card--movement">
            <button className="dashboard-modal__close" type="button" onClick={() => setShowMovementModal(false)}>
              ×
            </button>
            <h3>{movement.type === 'out' ? 'Saída de estoque' : 'Entrada de estoque'}</h3>
            <form className="dashboard-form" onSubmit={handleMovementSubmit}>
              <label>
                Quantidade
                <input
                  type="number"
                  min="1"
                  value={movement.quantity}
                  onChange={(event) => setMovement((prev) => ({ ...prev, quantity: event.target.value }))}
                  placeholder="Quantidade"
                  required
                />
              </label>
              <label>
                Observações
                <input
                  type="text"
                  value={movement.notes}
                  onChange={(event) => setMovement((prev) => ({ ...prev, notes: event.target.value }))}
                  placeholder="Observações (opcional)"
                />
              </label>
              {movementError ? <div className="dashboard-form__error">{movementError}</div> : null}
              <div className="dashboard-form__actions">
                <button className="btn-outline" type="button" onClick={() => setShowMovementModal(false)}>
                  Cancelar
                </button>
                <button className="btn-primary" type="submit" disabled={movementSubmitting}>
                  {movementSubmitting ? 'Salvando...' : 'Salvar'}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}

      {showHistoryModal ? (
        <div
          className="dashboard-modal"
          role="dialog"
          aria-modal="true"
          aria-label="Histórico de movimentações"
          onClick={(event) => {
            if (event.target === event.currentTarget) {
              setShowHistoryModal(false)
            }
          }}
        >
          <div className="dashboard-modal__card dashboard-modal__card--wide dashboard-modal__card--stock">
            <div className="dashboard-modal__header">
              <div>
                <p className="dashboard-kicker">Estoque</p>
                <h3>Movimentações dos últimos 30 dias</h3>
                <p className="dashboard-subtitle">Acompanhe entradas e saídas registradas recentemente.</p>
              </div>
              <button className="icon-button" type="button" onClick={() => setShowHistoryModal(false)} aria-label="Fechar">
                <i className="fa fa-times" aria-hidden="true" />
              </button>
            </div>
            {historyError ? <div className="dashboard-form__error">{historyError}</div> : null}
            <div className="data-table data-table--compact data-table--dashboard">
              <div className="stock-history-table">
              <table>
                <thead>
                  <tr>
                    <th>Data</th>
                    <th>Produto</th>
                    <th>Tipo</th>
                    <th>Quantidade</th>
                    <th>Observação</th>
                  </tr>
                </thead>
                <tbody>
                  {historyLoading ? (
                    <tr>
                      <td colSpan="5" className="stock-empty">
                        Carregando...
                      </td>
                    </tr>
                  ) : historyRecords.length ? (
                    historyRecords.map((record, index) => (
                      <tr key={`${record.date}-${index}`}>
                        <td>{record.date}</td>
                        <td>{record.product}</td>
                        <td>
                          <span
                            className={`stock-history-tag ${
                              record.type === 'Entrada' ? 'is-in' : 'is-out'
                            }`}
                          >
                            {record.type}
                          </span>
                        </td>
                        <td>{record.quantity}</td>
                        <td>{record.notes || '-'}</td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan="5" className="stock-empty">
                        Nenhuma movimentação recente.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}

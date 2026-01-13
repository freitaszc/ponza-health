import { useEffect, useMemo, useState } from 'react'
import { useRouter } from '../components/Router'

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

const planLabels = {
  monthly: 'Mensal',
  yearly: 'Anual',
  trial: 'Trial',
  standard: 'Padrão',
}

const formatDate = (value) => {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleDateString('pt-BR')
}

const formatSubscription = (user) => {
  const plan = planLabels[user.plan] || (user.plan || '').toUpperCase() || '—'
  const status = user.plan_status || '—'
  const planExpires = user.plan_expires ? `expira em ${formatDate(user.plan_expires)}` : ''
  const trialExpires = user.trial_expires ? `trial até ${formatDate(user.trial_expires)}` : ''
  const details = [plan, status, planExpires || trialExpires].filter(Boolean)
  return details.join(' • ')
}

export default function Admin() {
  const { navigate } = useRouter()
  const currentPath = typeof window !== 'undefined' ? window.location.pathname : '/admin'
  const [collapsed, setCollapsed] = useState(
    typeof window !== 'undefined' && localStorage.getItem('dashboardSidebar') === '1',
  )
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [busyUserId, setBusyUserId] = useState(null)
  const [busyAction, setBusyAction] = useState('')

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
    if (resolved === '/products') {
      return currentPath.startsWith('/products')
    }
    return currentPath === resolved
  }

  useEffect(() => {
    let active = true
    const load = async () => {
      setLoading(true)
      setError('')
      try {
        const response = await fetch('/api/admin/users', { credentials: 'include' })
        const payload = await response.json().catch(() => ({}))
        if (response.status === 403) {
          setError('Acesso restrito.')
          navigate('/index')
          return
        }
        if (!response.ok) {
          throw new Error(payload.error || 'Não foi possivel carregar usuários.')
        }
        if (!active) return
        const list = Array.isArray(payload.users) ? payload.users : []
        setUsers(list)
      } catch (err) {
        if (!active) return
        setError(err.message || 'Acesso restrito.')
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

  const filteredUsers = useMemo(() => {
    const search = searchInput.trim().toLowerCase()
    if (!search) return users
    return users.filter((user) =>
      [user.username, user.email].some((value) => (value || '').toLowerCase().includes(search)),
    )
  }, [users, searchInput])

  const handleToggleSidebar = () => {
    const next = !collapsed
    setCollapsed(next)
    localStorage.setItem('dashboardSidebar', next ? '1' : '0')
  }

  const handleExtend = async (userId, period) => {
    if (busyUserId) return
    setError('')
    setSuccess('')
    setBusyUserId(userId)
    setBusyAction(period)
    try {
      const response = await fetch(`/api/admin/users/${userId}/subscription`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ period }),
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok || payload.success === false) {
        throw new Error(payload.error || 'Nao foi possivel atualizar assinatura.')
      }
      const updated = payload.user
      setUsers((prev) => prev.map((item) => (item.id === userId ? updated : item)))
      setSuccess('Assinatura atualizada com sucesso.')
    } catch (err) {
      setError(err.message || 'Nao foi possivel atualizar assinatura.')
    } finally {
      setBusyUserId(null)
      setBusyAction('')
    }
  }

  const handleDelete = async (userId) => {
    if (busyUserId) return
    if (!window.confirm('Deseja remover este usuário? Essa ação é permanente.')) return
    setError('')
    setSuccess('')
    setBusyUserId(userId)
    setBusyAction('delete')
    try {
      const response = await fetch(`/api/admin/users/${userId}`, {
        method: 'DELETE',
        credentials: 'include',
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok || payload.success === false) {
        throw new Error(payload.error || 'Não foi possível remover usuário.')
      }
      setUsers((prev) => prev.filter((item) => item.id !== userId))
      setSuccess('Usuário removido com sucesso.')
    } catch (err) {
      setError(err.message || 'Não foi possível remover usuário.')
    } finally {
      setBusyUserId(null)
      setBusyAction('')
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
            <p className="dashboard-kicker">Admin</p>
            <h1>Gestão de usuários</h1>
            <p className="dashboard-subtitle">Acompanhe contas, assinaturas e controle acessos.</p>
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
        {success ? <div className="dashboard-alert dashboard-alert--success">{success}</div> : null}

        <section className="data-table data-table--spaced">
          <div className="data-table__head">
            <div className="data-table__tools">
              <label className="data-table__search">
                <i className="fa fa-search" aria-hidden="true" />
                <input
                  type="search"
                  placeholder="Buscar por nome ou e-mail"
                  value={searchInput}
                  onChange={(event) => setSearchInput(event.target.value)}
                />
              </label>
            </div>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Usuário</th>
                  <th>Email</th>
                  <th>Assinatura</th>
                  <th>Criado em</th>
                  <th>Ações</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan="5">Carregando usuários...</td>
                  </tr>
                ) : filteredUsers.length ? (
                  filteredUsers.map((user) => (
                    <tr key={user.id}>
                      <td>{user.username || '—'}</td>
                      <td>{user.email || '—'}</td>
                      <td>{formatSubscription(user)}</td>
                      <td>{formatDate(user.created_at)}</td>
                      <td>
                        <div className="admin-actions">
                          <button
                            type="button"
                            className="btn-outline btn-small"
                            onClick={() => handleExtend(user.id, 'month')}
                            disabled={busyUserId === user.id}
                          >
                            {busyUserId === user.id && busyAction === 'month' ? 'Aguarde...' : '+1 mes'}
                          </button>
                          <button
                            type="button"
                            className="btn-outline btn-small"
                            onClick={() => handleExtend(user.id, 'year')}
                            disabled={busyUserId === user.id}
                          >
                            {busyUserId === user.id && busyAction === 'year' ? 'Aguarde...' : '+1 ano'}
                          </button>
                          <button
                            type="button"
                            className="btn-outline btn-small btn-danger"
                            onClick={() => handleDelete(user.id)}
                            disabled={busyUserId === user.id}
                          >
                            {busyUserId === user.id && busyAction === 'delete' ? 'Removendo...' : 'Excluir'}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan="5">Nenhum usuário encontrado.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </div>
  )
}

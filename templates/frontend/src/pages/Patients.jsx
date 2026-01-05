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
  { label: 'Agenda', href: '/agenda', icon: 'fa-calendar' },
  { label: 'Pagamentos', href: '/payments', icon: 'fa-credit-card' },
]

const formatDateToISO = (value) => {
  const parts = (value || '').split('/')
  if (parts.length !== 3) return ''
  const [day, month, year] = parts
  if (!day || !month || !year) return ''
  return `${year}-${month}-${day}T00:00:00`
}

const maskDate = (value) => {
  const digits = (value || '').replace(/\D/g, '').slice(0, 8)
  if (digits.length <= 2) return digits
  if (digits.length <= 4) return `${digits.slice(0, 2)}/${digits.slice(2)}`
  return `${digits.slice(0, 2)}/${digits.slice(2, 4)}/${digits.slice(4)}`
}

const patientStatusFilters = [
  { label: 'Ativos', value: 'Ativo' },
  { label: 'Inativos', value: 'Inativo' },
]

export default function Patients() {
  const currentPath = typeof window !== 'undefined' ? window.location.pathname : '/catalog'
  const searchParams = typeof window !== 'undefined' ? new URLSearchParams(window.location.search) : null
  const initialSearch = searchParams?.get('search') || ''
  const statusParam = searchParams?.get('status') || ''
  const initialStatusSelection = patientStatusFilters.some((filter) => filter.value === statusParam)
    ? [statusParam]
    : patientStatusFilters.map((filter) => filter.value)

  const [collapsed, setCollapsed] = useState(
    typeof window !== 'undefined' && localStorage.getItem('dashboardSidebar') === '1',
  )
  const [patients, setPatients] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [searchInput, setSearchInput] = useState(initialSearch)
  const [statusInput, setStatusInput] = useState(initialStatusSelection)
  const [query, setQuery] = useState({
    search: initialSearch,
    status: initialStatusSelection.length === 1 ? initialStatusSelection[0] : '',
  })
  const [openMenuId, setOpenMenuId] = useState(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [modalPatientId, setModalPatientId] = useState('')
  const [modalDate, setModalDate] = useState('')
  const [modalNotes, setModalNotes] = useState('')
  const [modalError, setModalError] = useState('')
  const [modalSubmitting, setModalSubmitting] = useState(false)
  const [busyPatientId, setBusyPatientId] = useState(null)

  const sidebarNav = useMemo(() => navItems, [])
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
    return currentPath === resolved
  }

  useEffect(() => {
    const handleClick = () => setOpenMenuId(null)
    window.addEventListener('click', handleClick)
    return () => window.removeEventListener('click', handleClick)
  }, [])

  useEffect(() => {
    let active = true
    const cacheKey = buildCacheKey('patients', [query.search || 'all', query.status || 'all'])
    const cached = readCache(cacheKey)
    if (cached && Array.isArray(cached)) {
      setPatients(cached)
      setLoading(false)
    } else {
      setLoading(true)
    }
    const load = async () => {
      setError('')
      try {
        const params = new URLSearchParams()
        if (query.search) params.set('search', query.search)
        if (query.status) params.set('status', query.status)
        const response = await fetch(`/api/patients?${params.toString()}`, { credentials: 'include' })
        const payload = await response.json().catch(() => ({}))
        if (!response.ok || payload?.success === false) {
          throw new Error(payload?.error || 'Não foi possivel carregar os pacientes.')
        }
        if (!active) return
        const nextPatients = payload?.patients || []
        setPatients(nextPatients)
        writeCache(cacheKey, nextPatients)
      } catch (err) {
        if (!active) return
        setError(err.message || 'Não foi possivel carregar os pacientes.')
      } finally {
        if (!active) return
        setLoading(false)
      }
    }
    load()
    return () => {
      active = false
    }
  }, [query])

  const handleToggleSidebar = () => {
    const next = !collapsed
    setCollapsed(next)
    localStorage.setItem('dashboardSidebar', next ? '1' : '0')
  }

  const updateQuery = (nextQuery) => {
    setQuery(nextQuery)
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams()
      if (nextQuery.search) params.set('search', nextQuery.search)
      if (nextQuery.status) params.set('status', nextQuery.status)
      const qs = params.toString()
      const nextUrl = qs ? `${window.location.pathname}?${qs}` : window.location.pathname
      window.history.replaceState({}, '', nextUrl)
    }
  }

  const handleStatusFilter = (nextStatus) => {
    setStatusInput((prev) => {
      const next = prev.includes(nextStatus)
        ? prev.filter((value) => value !== nextStatus)
        : [...prev, nextStatus]
      return next.length ? next : patientStatusFilters.map((filter) => filter.value)
    })
  }

  useEffect(() => {
    const timeout = setTimeout(() => {
      updateQuery({
        search: searchInput.trim(),
        status: statusInput.length === 1 ? statusInput[0] : '',
      })
    }, 250)
    return () => clearTimeout(timeout)
  }, [searchInput, statusInput])

  const handleToggleStatus = async (patient) => {
    if (!patient) return
    const nextStatus = patient.status === 'Ativo' ? 'Inativo' : 'Ativo'
    setBusyPatientId(patient.id)
    try {
      const response = await fetch(`/toggle_patient_status/${patient.id}/${nextStatus}`, {
        method: 'POST',
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          Accept: 'application/json',
        },
        credentials: 'include',
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok || payload?.success === false) {
        throw new Error(payload?.message || 'Não foi possivel atualizar o status.')
      }
      setPatients((prev) =>
        prev.map((item) => (item.id === patient.id ? { ...item, status: payload.status || nextStatus } : item)),
      )
    } catch (err) {
      setError(err.message || 'Não foi possivel atualizar o status.')
    } finally {
      setBusyPatientId(null)
    }
  }

  const handleDelete = async (patientId) => {
    if (!patientId) return
    if (!window.confirm('Deseja realmente remover este paciente?')) return
    setBusyPatientId(patientId)
    try {
      const response = await fetch(`/delete_patient/${patientId}`, {
        method: 'POST',
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          Accept: 'application/json',
        },
        credentials: 'include',
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok || payload?.success === false) {
        throw new Error(payload?.message || 'Não foi possivel remover o paciente.')
      }
      setPatients((prev) => prev.filter((item) => item.id !== patientId))
    } catch (err) {
      setError(err.message || 'Não foi possivel remover o paciente.')
    } finally {
      setBusyPatientId(null)
    }
  }

  const openConsultationModal = (patientId) => {
    setModalError('')
    setModalPatientId(patientId ? String(patientId) : '')
    setModalDate('')
    setModalNotes('')
    setOpenMenuId(null)
    setModalOpen(true)
  }

  const closeConsultationModal = () => {
    if (modalSubmitting) return
    setModalOpen(false)
  }

  const handleSubmitConsultation = async () => {
    setModalError('')
    if (!modalPatientId) {
      setModalError('Selecione o paciente.')
      return
    }
    if (!modalDate) {
      setModalError('Informe a data no formato dd/mm/aaaa.')
      return
    }
    const isoDate = formatDateToISO(modalDate)
    if (!isoDate) {
      setModalError('Data invalida.')
      return
    }
    const selectedPatient = patients.find((patient) => String(patient.id) === String(modalPatientId))
    const patientName = selectedPatient?.name || ''
    setModalSubmitting(true)
    try {
      const response = await fetch('/api/add_event', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: `Consulta - ${patientName}`,
          start: isoDate,
          notes: modalNotes,
        }),
        credentials: 'include',
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok || payload?.success === false) {
        throw new Error(payload?.error || 'Não foi possivel salvar a consulta.')
      }
      setModalOpen(false)
    } catch (err) {
      setModalError(err.message || 'Não foi possivel salvar a consulta.')
    } finally {
      setModalSubmitting(false)
    }
  }

  const statusCounts = useMemo(() => {
    const activeCount = patients.filter((patient) => patient.status === 'Ativo').length
    return {
      all: patients.length,
      active: activeCount,
      inactive: patients.length - activeCount,
    }
  }, [patients])

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
            <p className="dashboard-kicker">Pacientes</p>
            <h1>Catálogo de pacientes</h1>
            <div className="dashboard-chips">
              <span>{patients.length} pacientes encontrados</span>
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
        {loading ? <div className="dashboard-loading">Carregando pacientes...</div> : null}

        {!loading ? (
          <div className="data-table data-table--spaced data-table--controls data-table--dropdowns data-table--dashboard">
            <div className="data-table__head">
              <div className="data-table__tools">
                <label className="data-table__search">
                  <i className="fa fa-search" aria-hidden="true" />
                  <input
                    type="search"
                    placeholder="Buscar paciente"
                    value={searchInput}
                    onChange={(event) => setSearchInput(event.target.value)}
                  />
                </label>
                <div className="data-table__filters" role="group" aria-label="Status do paciente">
                  {patientStatusFilters.map((filter) => {
                    const count =
                      filter.value === 'Ativo' ? statusCounts.active : statusCounts.inactive
                    return (
                      <button
                        key={filter.label}
                        type="button"
                        className={`filter-chip ${statusInput.includes(filter.value) ? 'is-active' : ''}`}
                        onClick={() => handleStatusFilter(filter.value)}
                      >
                        {filter.label}
                        <span className="filter-chip__count">{count}</span>
                      </button>
                    )
                  })}
                </div>
              </div>
              <div className="data-table__aside">
                <a className="btn-primary" href="/catalog/register">
                  Cadastrar paciente
                </a>
              </div>
            </div>
            <table className="patients-table">
              <thead>
                <tr>
                  <th>Paciente</th>
                  <th>Telefone</th>
                  <th>Medico</th>
                  <th>Status</th>
                  <th>Ações</th>
                </tr>
              </thead>
              <tbody>
                {patients.length ? (
                  patients.map((patient) => (
                    <tr key={patient.id}>
                      <td>
                        <div className="patient-cell">
                          <img
                            src={patient.profile_image || '/static/images/user-icon.png'}
                            alt=""
                            className="patient-avatar"
                          />
                          <div className="patient-info">
                            <span className="patient-name">{patient.name}</span>
                          </div>
                        </div>
                      </td>
                      <td>{patient.phone_primary || '—'}</td>
                      <td>{patient.doctor_name || '—'}</td>
                      <td>
                        <button
                          type="button"
                          className={`status-pill status-toggle ${patient.status === 'Ativo' ? 'status-pill--success' : 'status-pill--muted'}`}
                          disabled={busyPatientId === patient.id}
                          onClick={() => handleToggleStatus(patient)}
                        >
                          {patient.status || 'Inativo'}
                        </button>
                      </td>
                      <td>
                        <div className="table-actions">
                          <div className="dropdown" onClick={(event) => event.stopPropagation()}>
                            <button
                              type="button"
                              className="icon-button"
                              aria-label="Opcoes"
                              onClick={(event) => {
                                event.stopPropagation()
                                setOpenMenuId(openMenuId === patient.id ? null : patient.id)
                              }}
                            >
                              <i className="fa fa-ellipsis-h" aria-hidden="true" />
                            </button>
                            {openMenuId === patient.id ? (
                              <div className="dropdown-menu" role="menu">
                                <a href={`/patient_result/${patient.id}`}>Ver diagnostico</a>
                                <a href={`/edit_patient/${patient.id}`}>Editar informações</a>
                                <button type="button" onClick={() => openConsultationModal(patient.id)}>
                                  Adicionar consulta
                                </button>
                              </div>
                            ) : null}
                          </div>
                          <button
                            type="button"
                            className="icon-button is-danger"
                            onClick={() => handleDelete(patient.id)}
                            disabled={busyPatientId === patient.id}
                            aria-label="Remover paciente"
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
                      Nenhum paciente encontrado.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        ) : null}
      </main>

      {modalOpen ? (
        <div className="dashboard-modal" onClick={(event) => {
          if (event.target === event.currentTarget) closeConsultationModal()
        }}>
          <div className="dashboard-modal__card">
            <div className="dashboard-modal__header">
              <div>
                <p className="dashboard-kicker">Nova consulta</p>
                <h3>Adicionar consulta</h3>
              </div>
              <button className="icon-button" type="button" onClick={closeConsultationModal} aria-label="Fechar">
                <i className="fa fa-times" aria-hidden="true" />
              </button>
            </div>

            {modalError ? <div className="dashboard-alert">{modalError}</div> : null}

            <div className="dashboard-modal__body">
              <label className="dashboard-field">
                <span>Paciente</span>
                <select
                  className="dashboard-select"
                  value={modalPatientId}
                  onChange={(event) => setModalPatientId(event.target.value)}
                >
                  <option value="">Selecione</option>
                  {patients.map((patient) => (
                    <option key={patient.id} value={patient.id}>
                      {patient.name}
                    </option>
                  ))}
                </select>
              </label>

              <label className="dashboard-field">
                <span>Data</span>
                <input
                  className="dashboard-input"
                  placeholder="dd/mm/aaaa"
                  value={modalDate}
                  onChange={(event) => setModalDate(maskDate(event.target.value))}
                />
              </label>

              <label className="dashboard-field">
                <span>Observações</span>
                <textarea
                  className="dashboard-textarea"
                  rows="4"
                  value={modalNotes}
                  onChange={(event) => setModalNotes(event.target.value)}
                />
              </label>
            </div>

            <div className="dashboard-modal__actions">
              <button type="button" className="btn-primary" onClick={handleSubmitConsultation} disabled={modalSubmitting}>
                {modalSubmitting ? 'Salvando...' : 'Salvar consulta'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}

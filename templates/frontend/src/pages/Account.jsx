import { useEffect, useRef, useState } from 'react'

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

const emptyAccount = {
  user: {
    name: '',
    username: '',
    email: '',
    clinic_phone: '',
    clinic_address: '',
    profile_image: '/static/images/user-icon.png',
  },
  plan: {
    status: 'trial',
    name: null,
    label: null,
    expires_at: null,
    is_active: false,
  },
  trial: {
    active: false,
    remaining_days: 0,
    expires_at: null,
  },
  notifications_unread: 0,
  messages: [],
}

const formatDate = (dateValue) => {
  if (!dateValue) return '—'
  const [year, month, day] = String(dateValue).split('-')
  if (!year || !month || !day) return dateValue
  return `${day}/${month}/${year}`
}

export default function Account() {
  const [data, setData] = useState(emptyAccount)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showModal, setShowModal] = useState(false)
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('dashboardSidebar') === '1')
  const removePhotoFormRef = useRef(null)

  const currentPath = typeof window !== 'undefined' ? window.location.pathname : '/account'

  useEffect(() => {
    let active = true
    setLoading(true)
    fetch('/api/account', { credentials: 'same-origin' })
      .then((response) => {
        if (!response.ok) {
          throw new Error('Falha ao carregar a conta.')
        }
        return response.json()
      })
      .then((payload) => {
        if (!active) return
        setData({ ...emptyAccount, ...payload })
        setError('')
      })
      .catch(() => {
        if (!active) return
        setError('Não foi possível carregar os dados da conta.')
      })
      .finally(() => {
        if (!active) return
        setLoading(false)
      })

    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    if (!showModal) return
    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        setShowModal(false)
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [showModal])

  const sidebarNav = navItems

  const handleToggleSidebar = () => {
    const next = !collapsed
    setCollapsed(next)
    localStorage.setItem('dashboardSidebar', next ? '1' : '0')
  }

  const planStatusLabel = data.plan.is_active ? 'Ativo' : data.trial.active ? 'Teste' : 'Inativo'
  const planStatusClass = data.plan.is_active
    ? 'status-pill status-pill--success'
    : data.trial.active
      ? 'status-pill status-pill--warning'
      : 'status-pill status-pill--muted'

  return (
    <div className={`dashboard-shell account-shell ${collapsed ? 'is-collapsed' : ''}`}>
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
            <p className="dashboard-kicker">Minha conta</p>
            <h1>Gerencie seus dados e assinatura</h1>
          </div>
          <div className="dashboard-actions">
            <a className="dashboard-icon-btn" href="/index" aria-label="Voltar ao painel">
              <i className="fa fa-home" aria-hidden="true" />
            </a>
            <button className="dashboard-icon-btn" type="button" aria-label="Notificações">
              <i className="fa fa-bell" aria-hidden="true" />
              {data.notifications_unread ? <span className="badge">{data.notifications_unread}</span> : null}
            </button>
          </div>
        </header>

        {data.trial.active ? (
          <div className="dashboard-banner">
            <span>
              Seu teste termina em <strong>{data.trial.remaining_days} dias</strong>. Garanta acesso contínuo ativando
              seu plano.
            </span>
            <a href="/payments">Fazer upgrade</a>
          </div>
        ) : null}

        {error ? <div className="dashboard-alert">{error}</div> : null}
        {data.messages?.length ? (
          <div className="account-alerts">
            {data.messages.map((message, index) => (
              <div className={`account-alert account-alert--${message.category || 'info'}`} key={index}>
                {message.message}
              </div>
            ))}
          </div>
        ) : null}

        <div className="account-layout">
          <section className="dashboard-card account-card">
            <div className="account-card__head">
              <div>
                <p className="card-title">Informações pessoais</p>
                <h3>Seu perfil</h3>
              </div>
            </div>

            <div className="account-profile">
              <label className="account-avatar-label" htmlFor="profile_image">
                <img
                  src={data.user.profile_image || '/static/images/user-icon.png'}
                  alt="Foto do perfil"
                  className="account-avatar"
                />
              </label>
              <div className="account-profile__details">
                <strong>{data.user.name || data.user.username || 'Equipe Ponza'}</strong>
                <span>{data.user.email || 'Sem e-mail cadastrado'}</span>
                <div className="account-profile__actions">
                  <label className="account-remove-link" htmlFor="profile_image">
                    Alterar foto
                  </label>
                  <a
                    className="account-remove-link"
                    href="/remove_profile_image"
                    onClick={(event) => {
                      event.preventDefault()
                      if (window.confirm('Tem certeza que deseja remover sua foto de perfil?')) {
                        removePhotoFormRef.current?.submit()
                      }
                    }}
                  >
                    Remover foto
                  </a>
                </div>
              </div>
            </div>
            <form ref={removePhotoFormRef} method="post" action="/remove_profile_image" className="sr-only" />

            <form
              method="post"
              action="/update_personal_info"
              encType="multipart/form-data"
              className="account-form account-form--spaced account-form--stretch"
            >
              <input type="file" id="profile_image" name="profile_image" accept="image/*" className="sr-only" />
              <label>
                Nome
                <input type="text" name="name" defaultValue={data.user.name || ''} placeholder="Nome/Clínica" />
              </label>
              <label>
                Celular
                <input
                  type="text"
                  name="clinic_phone"
                  defaultValue={data.user.clinic_phone || ''}
                  placeholder="(00) 90000-0000"
                />
              </label>
              <label>
                Email
                <input type="email" name="email" defaultValue={data.user.email || ''} placeholder="email@exemplo.com" />
              </label>
              <label>
                Endereço da clínica
                <textarea
                  name="clinic_address"
                  rows="3"
                  defaultValue={data.user.clinic_address || ''}
                  placeholder="Rua, número, complemento, cidade e estado"
                />
              </label>

              <div className="account-actions">
                <button className="btn-primary" type="submit">
                  Salvar alterações
                </button>
                <button className="btn-primary" type="button" onClick={() => setShowModal(true)}>
                  Gerenciar assinatura
                </button>
              </div>
            </form>
          </section>

          <aside className="account-side">
            <div className="dashboard-card account-card">
              <p className="card-title">Resumo da assinatura</p>
              <h3>Plano {data.plan.label || 'Teste gratuito'}</h3>
              <div className="account-plan">
                <div>
                  <span>Status</span>
                  <strong>{data.plan.is_active ? 'Ativo' : data.trial.active ? 'Em teste' : 'Inativo'}</strong>
                </div>
                <div>
                  <span>Expira em</span>
                  <strong>{formatDate(data.plan.expires_at || data.trial.expires_at)}</strong>
                </div>
              </div>
              <div className="account-plan__actions">
                <a className="btn-primary btn-block" href="/payments">
                  Ver planos e pagamentos
                </a>
              </div>
            </div>

            <div className="dashboard-card account-card">
              <p className="card-title">Segurança</p>
              <h3>Alterar senha</h3>
              <form method="post" action="/update_password" className="account-form account-form--stretch">
                <label>
                  Senha atual
                  <input type="password" name="current_password" placeholder="Senha atual" />
                </label>
                <label>
                  Nova senha
                  <input type="password" name="new_password" placeholder="Nova senha" />
                </label>
                <label>
                  Confirmar senha
                  <input type="password" name="confirm_password" placeholder="Confirme a nova senha" />
                </label>
                <div className="account-actions">
                  <button className="btn-primary" type="submit">
                    Atualizar senha
                  </button>
                </div>
              </form>
            </div>
          </aside>
        </div>

        {loading ? <div className="dashboard-loading">Carregando conta…</div> : null}
      </main>

      {showModal ? (
        <div
          className="account-modal"
          role="dialog"
          aria-modal="true"
          aria-label="Gerenciar assinatura"
          onClick={(event) => {
            if (event.target === event.currentTarget) {
              setShowModal(false)
            }
          }}
        >
          <div className="account-modal__card">
            <button className="account-modal__close" type="button" onClick={() => setShowModal(false)}>
              ×
            </button>
            <h3>Gerenciar assinatura</h3>
            <p>Escolha uma das opções abaixo para alterar seu plano ou cancelar sua assinatura.</p>
            <div className="account-modal__actions">
              <a className="btn-primary" href="/subscribe_pay_mensal" target="_blank" rel="noreferrer">
                Assinar plano mensal
              </a>
              <a className="btn-primary" href="/subscribe_pay_anual" target="_blank" rel="noreferrer">
                Assinar plano anual
              </a>
              <form
                method="post"
                action="/cancel_subscription"
                onSubmit={(event) => {
                  if (!window.confirm('Tem certeza que deseja cancelar sua assinatura?')) {
                    event.preventDefault()
                  }
                }}
              >
                <button className="btn-primary btn-light" type="submit">
                  Cancelar assinatura
                </button>
              </form>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}

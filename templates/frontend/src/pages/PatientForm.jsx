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
  { label: 'Agenda', href: '/agenda', icon: 'fa-calendar' },
  { label: 'Pagamentos', href: '/payments', icon: 'fa-credit-card' },
]

const emptyForm = {
  name: '',
  birthdate: '',
  sex: '',
  email: '',
  cpf: '',
  phone_primary: '',
  phone_secondary: '',
  notes: '',
  cep: '',
  street: '',
  number: '',
  complement: '',
  district: '',
  city: '',
  state: '',
}

const maskDate = (value) => {
  const digits = (value || '').replace(/\D/g, '').slice(0, 8)
  if (digits.length <= 2) return digits
  if (digits.length <= 4) return `${digits.slice(0, 2)}/${digits.slice(2)}`
  return `${digits.slice(0, 2)}/${digits.slice(2, 4)}/${digits.slice(4)}`
}

export default function PatientForm() {
  const { params } = useRouter()
  const patientId = params?.patientId
  const isEdit = Boolean(patientId)
  const currentPath = typeof window !== 'undefined' ? window.location.pathname : '/catalog/register'

  const [collapsed, setCollapsed] = useState(
    typeof window !== 'undefined' && localStorage.getItem('dashboardSidebar') === '1',
  )
  const [form, setForm] = useState(emptyForm)
  const [profileImage, setProfileImage] = useState('/static/images/user-icon.png')
  const [file, setFile] = useState(null)
  const [loading, setLoading] = useState(isEdit)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

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
    if (!isEdit) return
    let active = true
    const load = async () => {
      setLoading(true)
      setError('')
      try {
        const response = await fetch(`/api/patients/${patientId}`, { credentials: 'include' })
        const payload = await response.json().catch(() => ({}))
        if (!response.ok || payload?.success === false) {
          throw new Error(payload?.error || 'Não foi possivel carregar o paciente.')
        }
        if (!active) return
        const patientData = payload?.patient || {}
        const normalizedSex = (patientData.sex || '').replace(new RegExp('n\\u00e3o', 'gi'), 'não')
        setForm({ ...emptyForm, ...patientData, sex: normalizedSex })
        setProfileImage(patientData.profile_image || '/static/images/user-icon.png')
      } catch (err) {
        if (!active) return
        setError(err.message || 'Não foi possivel carregar o paciente.')
      } finally {
        if (!active) return
        setLoading(false)
      }
    }
    load()
    return () => {
      active = false
    }
  }, [isEdit, patientId])

  const handleToggleSidebar = () => {
    const next = !collapsed
    setCollapsed(next)
    localStorage.setItem('dashboardSidebar', next ? '1' : '0')
  }

  const handleChange = (field, value) => {
    setForm((prev) => ({ ...prev, [field]: value }))
  }

  const handleFileChange = (event) => {
    const selected = event.target.files?.[0]
    if (!selected) return
    setFile(selected)
    setProfileImage(URL.createObjectURL(selected))
  }

  const handleRemovePhoto = async () => {
    if (!isEdit || !patientId) return
    setNotice('')
    setError('')
    try {
      const response = await fetch(`/patients/${patientId}/photo/delete`, {
        method: 'POST',
        credentials: 'include',
      })
      if (!response.ok) {
        throw new Error('Não foi possivel remover a foto.')
      }
      setProfileImage('/static/images/user-icon.png')
      setFile(null)
      setNotice('Foto removida.')
    } catch (err) {
      setError(err.message || 'Não foi possivel remover a foto.')
    }
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    setSaving(true)
    setError('')
    setNotice('')

    const formData = new FormData()
    Object.entries(form).forEach(([key, value]) => {
      formData.append(key, value ?? '')
    })
    if (file) {
      formData.append('profile_image', file)
    }

    try {
      const response = await fetch(isEdit ? `/api/patients/${patientId}` : '/api/patients', {
        method: 'POST',
        body: formData,
        credentials: 'include',
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok || payload?.success === false) {
        throw new Error(payload?.error || 'Não foi possivel salvar o paciente.')
      }
      window.location.href = '/catalog'
    } catch (err) {
      setError(err.message || 'Não foi possivel salvar o paciente.')
    } finally {
      setSaving(false)
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
            <p className="dashboard-kicker">Pacientes</p>
            <h1>{isEdit ? 'Editar paciente' : 'Cadastrar paciente'}</h1>
          </div>
          <div className="dashboard-actions">
            <a className="dashboard-icon-btn" href="/catalog" aria-label="Voltar ao catalogo">
              <i className="fa fa-arrow-left" aria-hidden="true" />
            </a>
          </div>
        </header>

        {error ? <div className="dashboard-alert">{error}</div> : null}
        {notice ? <div className="dashboard-alert dashboard-alert--success">{notice}</div> : null}
        {loading ? <div className="dashboard-loading">Carregando...</div> : null}

        {!loading ? (
          <form className="form-stack" onSubmit={handleSubmit}>
            <section className="dashboard-card dashboard-card--panel">
              <div className="card-title">Foto do paciente</div>
              <div className="profile-card">
                <div className="profile-avatar">
                  <img src={profileImage} alt="Foto do paciente" />
                </div>
                <div className="profile-actions">
                  <label className="btn-primary" htmlFor="profile_image">
                    Alterar foto
                  </label>
                  {isEdit ? (
                    <button type="button" className="btn-outline" onClick={handleRemovePhoto}>
                      Remover foto
                    </button>
                  ) : null}
                  <input
                    id="profile_image"
                    type="file"
                    accept="image/*"
                    onChange={handleFileChange}
                    hidden
                  />
                </div>
                <p className="profile-hint">Formatos aceitos: JPG ou PNG.</p>
              </div>
            </section>

            <section className="dashboard-card dashboard-card--panel">
              <div className="card-title">Informações pessoais</div>
              <div className="form-grid form-grid--2">
                <label className="dashboard-field">
                  <span>Nome completo *</span>
                  <input
                    className="dashboard-input"
                    value={form.name}
                    onChange={(event) => handleChange('name', event.target.value)}
                    required
                  />
                </label>
                <label className="dashboard-field">
                  <span>Data de nascimento</span>
                  <input
                    className="dashboard-input"
                    placeholder="dd/mm/aaaa"
                    value={form.birthdate}
                    onChange={(event) => handleChange('birthdate', maskDate(event.target.value))}
                    required={!isEdit}
                  />
                </label>
              </div>

              <div className="form-grid">
                <label className="dashboard-field">
                  <span>Sexo</span>
                  <select
                    className="dashboard-select"
                    value={form.sex}
                    onChange={(event) => handleChange('sex', event.target.value)}
                    required={!isEdit}
                  >
                    <option value="">Selecione</option>
                    <option value="Feminino">Feminino</option>
                    <option value="Masculino">Masculino</option>
                    <option value="Outro">Outro</option>
                    <option value="Prefiro não informar">Prefiro não informar</option>
                  </select>
                </label>
                <label className="dashboard-field">
                  <span>Email</span>
                  <input
                    className="dashboard-input"
                    type="email"
                    value={form.email}
                    onChange={(event) => handleChange('email', event.target.value)}
                  />
                </label>
                <label className="dashboard-field">
                  <span>CPF</span>
                  <input
                    className="dashboard-input"
                    value={form.cpf}
                    onChange={(event) => handleChange('cpf', event.target.value)}
                  />
                </label>
              </div>

              <div className="form-grid">
                <label className="dashboard-field">
                  <span>Celular *</span>
                  <input
                    className="dashboard-input"
                    value={form.phone_primary}
                    onChange={(event) => handleChange('phone_primary', event.target.value)}
                    required={!isEdit}
                  />
                </label>
                <label className="dashboard-field">
                  <span>Celular secundário</span>
                  <input
                    className="dashboard-input"
                    value={form.phone_secondary}
                    onChange={(event) => handleChange('phone_secondary', event.target.value)}
                  />
                </label>
              </div>
            </section>

            <section className="dashboard-card dashboard-card--panel">
              <div className="card-title">Endereço</div>
              <div className="form-grid">
                <label className="dashboard-field">
                  <span>CEP</span>
                  <input
                    className="dashboard-input"
                    value={form.cep}
                    onChange={(event) => handleChange('cep', event.target.value)}
                  />
                </label>
                <label className="dashboard-field">
                  <span>Rua</span>
                  <input
                    className="dashboard-input"
                    value={form.street}
                    onChange={(event) => handleChange('street', event.target.value)}
                  />
                </label>
                <label className="dashboard-field">
                  <span>Número</span>
                  <input
                    className="dashboard-input"
                    value={form.number}
                    onChange={(event) => handleChange('number', event.target.value)}
                  />
                </label>
                <label className="dashboard-field">
                  <span>Complemento</span>
                  <input
                    className="dashboard-input"
                    value={form.complement}
                    onChange={(event) => handleChange('complement', event.target.value)}
                  />
                </label>
              </div>
              <div className="form-grid">
                <label className="dashboard-field">
                  <span>Bairro</span>
                  <input
                    className="dashboard-input"
                    value={form.district}
                    onChange={(event) => handleChange('district', event.target.value)}
                  />
                </label>
                <label className="dashboard-field">
                  <span>Cidade</span>
                  <input
                    className="dashboard-input"
                    value={form.city}
                    onChange={(event) => handleChange('city', event.target.value)}
                  />
                </label>
                <label className="dashboard-field">
                  <span>Estado</span>
                  <input
                    className="dashboard-input"
                    value={form.state}
                    onChange={(event) => handleChange('state', event.target.value)}
                  />
                </label>
              </div>
            </section>

            <section className="dashboard-card dashboard-card--panel">
              <div className="card-title">Observações</div>
              <label className="dashboard-field">
                <span>Notas clínicas</span>
                <textarea
                  className="dashboard-textarea"
                  rows="5"
                  value={form.notes}
                  onChange={(event) => handleChange('notes', event.target.value)}
                />
              </label>
            </section>

            <div className="form-actions">
              <a className="btn-outline" href="/catalog">
                Cancelar
              </a>
              <button type="submit" className="btn-primary" disabled={saving}>
                {saving ? 'Salvando...' : 'Salvar paciente'}
              </button>
            </div>
          </form>
        ) : null}
      </main>
    </div>
  )
}

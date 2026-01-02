import { useMemo, useRef, useState } from 'react'
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

export default function Upload() {
  const { navigate } = useRouter()
  const currentPath = typeof window !== 'undefined' ? window.location.pathname : '/upload'
  const initialCollapsed =
    typeof window !== 'undefined' && localStorage.getItem('dashboardSidebar') === '1'
  const initialError =
    typeof window !== 'undefined' ? new URLSearchParams(window.location.search).get('error') : ''

  const [collapsed, setCollapsed] = useState(initialCollapsed)
  const [mode, setMode] = useState('pdf')
  const [fileName, setFileName] = useState('')
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState(initialError || '')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [sendDoctor, setSendDoctor] = useState(false)
  const [sendPatient, setSendPatient] = useState(false)

  const fileInputRef = useRef(null)

  const sidebarNav = useMemo(() => navItems, [])

  const handleToggleSidebar = () => {
    const next = !collapsed
    setCollapsed(next)
    localStorage.setItem('dashboardSidebar', next ? '1' : '0')
  }

  const handleModeChange = (nextMode) => {
    setMode(nextMode)
    setError('')
  }

  const updateFileName = (file) => {
    if (!file) {
      setFileName('')
      return
    }
    setFileName(file.name)
  }

  const handleFileChange = (event) => {
    const file = event.target.files?.[0]
    updateFileName(file)
  }

  const handleDrop = (event) => {
    event.preventDefault()
    setDragging(false)
    const file = event.dataTransfer.files?.[0]
    if (!file) return
    if (!file.type.includes('pdf') && !file.name.toLowerCase().endsWith('.pdf')) {
      setError('Por favor, envie um arquivo PDF.')
      return
    }
    if (fileInputRef.current) {
      const transfer = new DataTransfer()
      transfer.items.add(file)
      fileInputRef.current.files = transfer.files
    }
    updateFileName(file)
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    setError('')

    if (mode === 'pdf' && !fileInputRef.current?.files?.length) {
      setError('Selecione um PDF antes de enviar.')
      return
    }

    const formData = new FormData(event.currentTarget)
    setIsSubmitting(true)

    try {
      const response = await fetch('/api/upload', {
        method: 'POST',
        body: formData,
        credentials: 'include',
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok || payload.success === false) {
        setError(payload.error || 'Não foi possível processar o envio.')
        return
      }
      if (payload.redirect_url) {
        navigate(payload.redirect_url)
        return
      }
      setError('Resposta inválida do servidor.')
    } catch (err) {
      setError('Não foi possível conectar ao servidor. Tente novamente.')
    } finally {
      setIsSubmitting(false)
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

      <main className="dashboard-main lab-main">
        <div className="lab-container">
          <header className="lab-hero">
            <img src="/static/images/PonzaLab.svg" alt="Ponza Lab" className="lab-logo" />
            <p className="lab-subtitle">
              Envie um PDF de exames para análise automática ou insira os dados manualmente.
            </p>
          </header>

          <div className="lab-toggle">
            <button
              type="button"
              className={`lab-toggle__btn ${mode === 'pdf' ? 'is-active' : ''}`}
              onClick={() => handleModeChange('pdf')}
            >
              Usar PDF
            </button>
            <button
              type="button"
              className={`lab-toggle__btn ${mode === 'manual' ? 'is-active' : ''}`}
              onClick={() => handleModeChange('manual')}
            >
              Inserir manualmente
            </button>
          </div>

          {error ? <div className="lab-alert">{error}</div> : null}

          {mode === 'pdf' ? (
            <form className="lab-panel" onSubmit={handleSubmit} encType="multipart/form-data">
              <input type="hidden" name="use_ai" value="1" />
              <input ref={fileInputRef} type="file" name="pdf_file" accept="application/pdf" hidden onChange={handleFileChange} />

              <div className="lab-panel__header">
                <span className="lab-panel__eyebrow">Exame para análise</span>
                <h2 className="lab-panel__title">Envie um PDF de exames</h2>
                <p className="lab-panel__desc">Organize os resultados em minutos com uma leitura clara e objetiva.</p>
              </div>

              <div
                className={`lab-dropzone ${dragging ? 'is-dragging' : ''}`}
                onClick={() => fileInputRef.current?.click()}
                onDragOver={(event) => {
                  event.preventDefault()
                  setDragging(true)
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={handleDrop}
              >
                <div className="lab-dropzone__icon">
                  <i className="fa fa-cloud-upload" aria-hidden="true" />
                </div>
                <div>
                  <div className="lab-dropzone__title">
                    {fileName || 'Clique ou arraste um PDF aqui'}
                  </div>
                  <div className="lab-dropzone__hint">Arquivos em PDF (laudos laboratoriais).</div>
                </div>
              </div>

              <div className="lab-send">
                <label className="lab-checkbox">
                  <input
                    type="checkbox"
                    name="send_doctor"
                    value="1"
                    checked={sendDoctor}
                    onChange={(event) => setSendDoctor(event.target.checked)}
                  />
                  Enviar ao médico
                </label>
                {sendDoctor ? (
                  <div className="lab-send__fields">
                    <input type="text" name="doctor_name" placeholder="Nome do médico" className="lab-input" />
                    <input type="text" name="doctor_phone" placeholder="Telefone WhatsApp do médico" className="lab-input" />
                  </div>
                ) : null}

                <label className="lab-checkbox">
                  <input
                    type="checkbox"
                    name="send_patient"
                    value="1"
                    checked={sendPatient}
                    onChange={(event) => setSendPatient(event.target.checked)}
                  />
                  Enviar ao paciente
                </label>
                {sendPatient ? (
                  <div className="lab-send__fields">
                    <input type="text" name="patient_name" placeholder="Nome do paciente" className="lab-input" />
                    <input type="text" name="patient_phone" placeholder="Telefone WhatsApp do paciente" className="lab-input" />
                  </div>
                ) : null}
              </div>

              <div className="lab-actions">
                <button className="lab-primary" type="submit" disabled={isSubmitting}>
                  {isSubmitting ? 'Analisando...' : 'Analisar com IA'}
                </button>
              </div>
            </form>
          ) : (
            <form className="lab-panel" onSubmit={handleSubmit}>
              <input type="hidden" name="manual_entry" value="1" />
              <input type="hidden" name="use_ai" value="1" />

              <div className="lab-panel__header">
                <span className="lab-panel__eyebrow">Dados do paciente</span>
                <h2 className="lab-panel__title">Inserção manual</h2>
                <p className="lab-panel__desc">Cole os resultados do laudo e finalize a análise com um clique.</p>
              </div>

              <div className="lab-grid">
                <label className="lab-field">
                  <span>Nome completo</span>
                  <input type="text" name="name" required placeholder="Ex.: Maria Aparecida Silva" className="lab-input" />
                </label>
                <label className="lab-field">
                  <span>Idade</span>
                  <input type="number" name="age" min="0" max="130" required placeholder="Ex.: 34" className="lab-input" />
                </label>
                <label className="lab-field">
                  <span>Sexo</span>
                  <select name="gender" required className="lab-select" defaultValue="">
                    <option value="" disabled>
                      Selecione
                    </option>
                    <option value="Feminino">Feminino</option>
                    <option value="Masculino">Masculino</option>
                    <option value="Outro">Outro</option>
                  </select>
                </label>
                <label className="lab-field">
                  <span>Telefone</span>
                  <input type="tel" name="phone" required placeholder="Ex.: (11) 91234-5678" className="lab-input" />
                </label>
              </div>

              <label className="lab-field lab-field--full">
                <span>Resultados (cole os valores do laudo)</span>
                <textarea
                  name="lab_results"
                  required
                  rows={8}
                  placeholder="Ex.: Hemácias: 3,85 milhões/mm³..."
                  className="lab-textarea"
                />
              </label>

              <div className="lab-actions">
                <button className="lab-primary" type="submit" disabled={isSubmitting}>
                  {isSubmitting ? 'Analisando...' : 'Analisar com IA'}
                </button>
              </div>
            </form>
          )}
        </div>
      </main>
    </div>
  )
}

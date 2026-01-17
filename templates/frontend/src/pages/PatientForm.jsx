import { useEffect, useMemo, useState } from 'react'
import { useRouter } from '../components/Router'
import { clearCache } from '../utils/cache'

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

const emptyForm = {
  name: '',
  birthdate: '',
  sex: '',
  email: '',
  cpf: '',
  marital_status: '',
  father_name: '',
  mother_name: '',
  education_level: '',
  profession: '',
  monthly_income: '',
  special_needs: '',
  chronic_conditions: '',
  emergency_contact_name: '',
  emergency_contact_phone: '',
  has_health_plan: false,
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

const formSections = [
  { id: 'sec-exames', label: 'Exames' },
  { id: 'sec-foto', label: 'Foto' },
  { id: 'sec-pessoais', label: 'Pessoais' },
  { id: 'sec-endereco', label: 'Endereço' },
  { id: 'sec-complementares', label: 'Complementares' },
  { id: 'sec-observacoes', label: 'Observações' },
]

const maritalStatusOptions = [
  'Solteiro(a)',
  'Casado(a)',
  'Separado(a)',
  'Divorciado(a)',
  'Viúvo(a)',
  'União estável',
  'Prefiro não informar',
]

const educationOptions = [
  'Fundamental incompleto',
  'Fundamental completo',
  'Médio incompleto',
  'Médio completo',
  'Superior incompleto',
  'Superior completo',
  'Pós-graduação',
  'Mestrado',
  'Doutorado',
  'Prefiro não informar',
]

const incomeOptions = [
  'Até 1 salário mínimo',
  '1 a 2 salários mínimos',
  '2 a 5 salários mínimos',
  '5 a 10 salários mínimos',
  'Acima de 10 salários mínimos',
  'Prefiro não informar',
]

const specialNeedsOptions = [
  'Não',
  'Física',
  'Auditiva',
  'Visual',
  'Intelectual',
  'Outra',
  'Prefiro não informar',
]

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
  const [examHistory, setExamHistory] = useState([])
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [expandedExam, setExpandedExam] = useState(null)
  const [expandedExamDetail, setExpandedExamDetail] = useState(null)
  const [loadingExamDetail, setLoadingExamDetail] = useState(false)
  const [uploadingExam, setUploadingExam] = useState(false)
  const [uploadProgress, setUploadProgress] = useState('')

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
    const loadExamHistory = async () => {
      setLoadingHistory(true)
      try {
        const response = await fetch(`/api/patient/${patientId}/exam_history`, { credentials: 'include' })
        const payload = await response.json().catch(() => ({}))
        if (!active) return
        if (response.ok && payload?.success) {
          setExamHistory(payload?.history || [])
        }
      } catch {
        // Silently fail - exam history is optional
      } finally {
        if (!active) return
        setLoadingHistory(false)
      }
    }
    load()
    loadExamHistory()
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

  const handleExamUpload = async (event) => {
    const selectedFile = event.target.files?.[0]
    if (!selectedFile || !patientId) return
    
    setUploadingExam(true)
    setUploadProgress('Enviando arquivo...')
    setError('')
    setNotice('')

    const formData = new FormData()
    formData.append('file', selectedFile)
    formData.append('patient_id', patientId)
    formData.append('skip_patient_info', 'true') // Tell backend to use existing patient

    try {
      const response = await fetch('/api/upload', {
        method: 'POST',
        body: formData,
        credentials: 'include',
      })

      // Handle streaming response
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let result = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        result += decoder.decode(value, { stream: true })
        
        // Parse progress updates
        const lines = result.split('\n')
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6))
              if (data.status) {
                setUploadProgress(data.status)
              }
              if (data.redirect) {
                // Analysis complete - reload exam history
                setNotice('Exame analisado com sucesso!')
                setUploadProgress('')
                // Reload exam history
                const historyResponse = await fetch(`/api/patient/${patientId}/exam_history`, { credentials: 'include' })
                const historyPayload = await historyResponse.json().catch(() => ({}))
                if (historyResponse.ok && historyPayload?.success) {
                  setExamHistory(historyPayload?.history || [])
                }
              }
              if (data.error) {
                throw new Error(data.error)
              }
            } catch (e) {
              // Ignore parse errors for incomplete chunks
            }
          }
        }
      }
    } catch (err) {
      setError(err.message || 'Não foi possível enviar o exame.')
    } finally {
      setUploadingExam(false)
      setUploadProgress('')
      // Reset file input
      event.target.value = ''
    }
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
    if (saving) return
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
      // Clear patients cache so the list shows updated data
      clearCache('patients')
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
            <p className="dashboard-kicker">Pacientes</p>
            <h1>{isEdit ? (form.name || 'Carregando...') : 'Cadastrar paciente'}</h1>
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
          <form className="form-stack" onSubmit={handleSubmit} aria-busy={saving}>
            <div className="form-section-nav" aria-label="Seções do cadastro">
              <div className="form-section-nav__label">Seções</div>
              <div className="form-section-nav__buttons" role="navigation" aria-label="Atalhos das seções">
                {formSections.map((section) => {
                  // Hide exames section for new patients
                  if (section.id === 'sec-exames' && !isEdit) return null
                  return (
                    <a key={section.id} className="form-section-nav__btn" href={`#${section.id}`}>
                      {section.label}
                    </a>
                  )
                })}
              </div>
            </div>

            {isEdit && (
              <section className="dashboard-card dashboard-card--panel" id="sec-exames">
                <div className="card-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <i className="fa fa-flask" style={{ marginRight: '8px' }} />
                    Histórico de Exames
                    {examHistory.length > 0 && (
                      <span style={{ fontWeight: 'normal', fontSize: '0.85em', marginLeft: '8px', color: '#666' }}>
                        ({examHistory.length} {examHistory.length === 1 ? 'registro' : 'registros'})
                      </span>
                    )}
                  </div>
                  <label className="btn-primary" style={{ fontSize: '0.85em', cursor: 'pointer' }}>
                    <i className="fa fa-plus" style={{ marginRight: '6px' }} />
                    Novo exame
                    <input
                      type="file"
                      accept=".pdf"
                      onChange={handleExamUpload}
                      disabled={uploadingExam}
                      hidden
                    />
                  </label>
                </div>
                
                {uploadingExam && (
                  <div className="dashboard-loading" style={{ padding: '16px', textAlign: 'center', background: '#f0f7ff', borderRadius: '8px', marginBottom: '16px' }}>
                    <span className="result-spinner" style={{ marginRight: '8px' }} />
                    {uploadProgress || 'Analisando exame...'}
                  </div>
                )}
                
                {loadingHistory ? (
                  <div className="dashboard-loading" style={{ padding: '20px', textAlign: 'center' }}>
                    <span className="result-spinner" style={{ marginRight: '8px' }} />
                    Carregando histórico...
                  </div>
                ) : examHistory.length === 0 && !uploadingExam ? (
                  <div className="empty-state" style={{ padding: '24px', textAlign: 'center', color: '#666' }}>
                    <i className="fa fa-file-text-o" style={{ fontSize: '32px', marginBottom: '12px', opacity: 0.5 }} />
                    <p>Nenhum exame registrado para este paciente.</p>
                    <label className="btn-outline" style={{ marginTop: '12px', cursor: 'pointer', display: 'inline-block' }}>
                      <i className="fa fa-upload" style={{ marginRight: '6px' }} />
                      Enviar primeiro exame
                      <input
                        type="file"
                        accept=".pdf"
                        onChange={handleExamUpload}
                        disabled={uploadingExam}
                        hidden
                      />
                    </label>
                  </div>
                ) : examHistory.length > 0 ? (
                  <div className="exam-history-list">
                    {examHistory.map((exam, index) => {
                      const isExpanded = expandedExam === exam.id
                      const examDate = exam.exam_date ? new Date(exam.exam_date).toLocaleDateString('pt-BR') : 'Data não informada'
                      const hasAbnormal = exam.abnormal_count > 0
                      const detail = expandedExamDetail && expandedExamDetail.id === exam.id ? expandedExamDetail : null
                      
                      const handleExpand = async () => {
                        if (isExpanded) {
                          setExpandedExam(null)
                          setExpandedExamDetail(null)
                        } else {
                          setExpandedExam(exam.id)
                          setLoadingExamDetail(true)
                          try {
                            const res = await fetch(`/api/patient/${patientId}/exam_history/${exam.id}`, { credentials: 'include' })
                            const data = await res.json()
                            if (data.success) {
                              setExpandedExamDetail(data)
                            }
                          } catch (err) {
                            console.error('Error fetching exam detail:', err)
                          } finally {
                            setLoadingExamDetail(false)
                          }
                        }
                      }
                      
                      return (
                        <div key={exam.id} className={`exam-history-item ${isExpanded ? 'is-expanded' : ''}`}>
                          <div 
                            className="exam-history-header"
                            onClick={handleExpand}
                            style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', background: index % 2 === 0 ? '#fafafa' : '#fff', borderRadius: '8px', marginBottom: '4px' }}
                          >
                            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                              <i className={`fa ${isExpanded ? 'fa-chevron-down' : 'fa-chevron-right'}`} style={{ width: '16px', color: '#888' }} />
                              <div>
                                <strong style={{ color: '#333' }}>{examDate}</strong>
                                <span style={{ marginLeft: '12px', fontSize: '0.9em', color: '#666' }}>
                                  {exam.total_exams} {exam.total_exams === 1 ? 'exame' : 'exames'}
                                </span>
                              </div>
                            </div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                              {hasAbnormal ? (
                                <span className="lab-status lab-status--alto" style={{ fontSize: '0.8em' }}>
                                  {exam.abnormal_count} alterado{exam.abnormal_count > 1 ? 's' : ''}
                                </span>
                              ) : (
                                <span className="lab-status lab-status--normal" style={{ fontSize: '0.8em' }}>
                                  Todos normais
                                </span>
                              )}
                              <a 
                                href={`/patient_result/${patientId}?history_id=${exam.id}`}
                                className="icon-button"
                                onClick={(e) => e.stopPropagation()}
                                title="Ver análise completa"
                              >
                                <i className="fa fa-external-link" />
                              </a>
                            </div>
                          </div>
                          {isExpanded && (
                            <div className="exam-history-details" style={{ padding: '16px', background: '#f8fafc', borderRadius: '0 0 8px 8px', marginTop: '-4px', marginBottom: '8px' }}>
                              {loadingExamDetail ? (
                                <div style={{ textAlign: 'center', padding: '20px' }}>
                                  <span className="result-spinner" style={{ marginRight: '8px' }} />
                                  Carregando resultados...
                                </div>
                              ) : detail && detail.all_results && detail.all_results.length > 0 ? (
                                <>
                                  {detail.resumo_clinico && (
                                    <div style={{ marginBottom: '16px', padding: '12px', background: '#e8f4fd', borderRadius: '8px', borderLeft: '3px solid #0f63ff' }}>
                                      <strong style={{ fontSize: '0.85em', color: '#0f63ff' }}>Resumo Clínico:</strong>
                                      <p style={{ margin: '6px 0 0', color: '#333', lineHeight: 1.5 }}>{detail.resumo_clinico}</p>
                                    </div>
                                  )}
                                  <div style={{ overflowX: 'auto' }}>
                                    <table className="exam-results-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.9em' }}>
                                      <thead>
                                        <tr style={{ background: '#e2e8f0', textAlign: 'left' }}>
                                          <th style={{ padding: '10px 12px', fontWeight: '600', borderRadius: '6px 0 0 0' }}>Exame</th>
                                          <th style={{ padding: '10px 12px', fontWeight: '600' }}>Resultado</th>
                                          <th style={{ padding: '10px 12px', fontWeight: '600' }}>Referência</th>
                                          <th style={{ padding: '10px 12px', fontWeight: '600', borderRadius: '0 6px 0 0' }}>Status</th>
                                        </tr>
                                      </thead>
                                      <tbody>
                                        {detail.all_results.map((result, idx) => {
                                          const status = (result.status || result.estado || '').toLowerCase()
                                          const isAbnormal = status === 'alto' || status === 'baixo' || status === 'alterado'
                                          return (
                                            <tr key={idx} style={{ background: isAbnormal ? 'rgba(239, 68, 68, 0.06)' : idx % 2 === 0 ? '#fff' : '#f8fafc' }}>
                                              <td style={{ padding: '10px 12px', borderBottom: '1px solid #e2e8f0' }}>
                                                <strong style={{ color: isAbnormal ? '#dc2626' : '#333' }}>{result.nome || result.name}</strong>
                                              </td>
                                              <td style={{ padding: '10px 12px', borderBottom: '1px solid #e2e8f0' }}>
                                                <span style={{ fontWeight: '600', color: isAbnormal ? '#dc2626' : '#333' }}>
                                                  {result.valor || result.value} {result.unidade || result.unit || ''}
                                                </span>
                                              </td>
                                              <td style={{ padding: '10px 12px', borderBottom: '1px solid #e2e8f0', color: '#666' }}>
                                                {result.referencia || result.reference || result.reference_display || '—'}
                                              </td>
                                              <td style={{ padding: '10px 12px', borderBottom: '1px solid #e2e8f0' }}>
                                                <span className={`lab-status lab-status--${status || 'indefinido'}`} style={{ fontSize: '0.85em' }}>
                                                  {status === 'normal' ? 'Normal' : status === 'alto' ? 'Alto' : status === 'baixo' ? 'Baixo' : status === 'alterado' ? 'Alterado' : 'N/D'}
                                                </span>
                                              </td>
                                            </tr>
                                          )
                                        })}
                                      </tbody>
                                    </table>
                                  </div>
                                  <div style={{ marginTop: '16px', paddingTop: '12px', borderTop: '1px solid #e2e8f0', display: 'flex', justifyContent: 'center' }}>
                                    <a 
                                      href={`/patient_result/${patientId}?history_id=${exam.id}`}
                                      className="btn-primary"
                                      style={{ fontSize: '0.9em' }}
                                    >
                                      <i className="fa fa-file-text-o" style={{ marginRight: '6px' }} />
                                      Análise Completa com IA
                                    </a>
                                  </div>
                                </>
                              ) : (
                                <div style={{ textAlign: 'center', padding: '20px', color: '#666' }}>
                                  Nenhum resultado detalhado disponível.
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                ) : null}
              </section>
            )}

            <section className="profile-section" id="sec-foto">
              <div className="card-title">Foto do paciente</div>
              <div className="profile-card">
                <div className="profile-avatar">
                  <img src={profileImage} alt="Foto do paciente" />
                </div>
                <div className="profile-actions">
                  <label className="form-section-nav__btn" htmlFor="profile_image">
                    Alterar foto
                  </label>
                  {isEdit ? (
                    <button type="button" className="form-section-nav__btn" onClick={handleRemovePhoto}>
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

            <section className="dashboard-card dashboard-card--panel" id="sec-pessoais">
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
                  <span>Estado civil</span>
                  <select
                    className="dashboard-select"
                    value={form.marital_status}
                    onChange={(event) => handleChange('marital_status', event.target.value)}
                  >
                    <option value="">Selecione</option>
                    {maritalStatusOptions.map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
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
                  <span>Email</span>
                  <input
                    className="dashboard-input"
                    type="email"
                    value={form.email}
                    onChange={(event) => handleChange('email', event.target.value)}
                  />
                </label>
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

              <div className="form-grid form-grid--2">
                <label className="dashboard-field">
                  <span>Nome do pai</span>
                  <input
                    className="dashboard-input"
                    value={form.father_name}
                    onChange={(event) => handleChange('father_name', event.target.value)}
                  />
                </label>
                <label className="dashboard-field">
                  <span>Nome da mãe</span>
                  <input
                    className="dashboard-input"
                    value={form.mother_name}
                    onChange={(event) => handleChange('mother_name', event.target.value)}
                  />
                </label>
              </div>
            </section>

            <section className="dashboard-card dashboard-card--panel" id="sec-endereco">
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

            <section className="dashboard-card dashboard-card--panel" id="sec-complementares">
              <div className="card-title">Informações complementares</div>
              <div className="form-grid" style={{ gridTemplateColumns: 'repeat(4, minmax(0, 1fr))' }}>
                <label className="dashboard-field">
                  <span>Escolaridade</span>
                  <select
                    className="dashboard-select"
                    value={form.education_level}
                    onChange={(event) => handleChange('education_level', event.target.value)}
                  >
                    <option value="">Selecione</option>
                    {educationOptions.map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="dashboard-field">
                  <span>Profissão</span>
                  <input
                    className="dashboard-input"
                    value={form.profession}
                    onChange={(event) => handleChange('profession', event.target.value)}
                  />
                </label>
                <label className="dashboard-field">
                  <span>Renda mensal</span>
                  <select
                    className="dashboard-select"
                    value={form.monthly_income}
                    onChange={(event) => handleChange('monthly_income', event.target.value)}
                  >
                    <option value="">Selecione</option>
                    {incomeOptions.map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="dashboard-field">
                  <span>Necessidades especiais</span>
                  <select
                    className="dashboard-select"
                    value={form.special_needs}
                    onChange={(event) => handleChange('special_needs', event.target.value)}
                  >
                    <option value="">Selecione</option>
                    {specialNeedsOptions.map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="form-grid">
                <label className="dashboard-field" style={{ gridColumn: '1 / -1' }}>
                  <span>Doenças ou problemas crônicos</span>
                  <textarea
                    className="dashboard-textarea"
                    rows="2"
                    value={form.chronic_conditions}
                    onChange={(event) => handleChange('chronic_conditions', event.target.value)}
                  />
                </label>
              </div>
              <div className="form-grid">
                <label className="dashboard-field">
                  <span>Nome contato de emergência</span>
                  <input
                    className="dashboard-input"
                    value={form.emergency_contact_name}
                    onChange={(event) => handleChange('emergency_contact_name', event.target.value)}
                  />
                </label>
                <label className="dashboard-field">
                  <span>Contato de emergência</span>
                  <input
                    className="dashboard-input"
                    type="tel"
                    value={form.emergency_contact_phone}
                    onChange={(event) => handleChange('emergency_contact_phone', event.target.value)}
                  />
                </label>
              </div>
              <div className="toggle-center">
                <label className="toggle-control">
                  <span className="toggle-label">Plano de saúde</span>
                  <input
                    type="checkbox"
                    checked={form.has_health_plan}
                    onChange={(event) => handleChange('has_health_plan', event.target.checked)}
                  />
                  <span className="toggle-track">
                    <span className="toggle-thumb" />
                  </span>
                </label>
              </div>
            </section>

            <section className="dashboard-card dashboard-card--panel" id="sec-observacoes">
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

            <div className="form-actions" style={{ justifyContent: 'center' }}>
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

      {saving ? (
        <div className="dashboard-modal dashboard-loading-modal" role="dialog" aria-modal="true">
          <div className="dashboard-modal__card dashboard-loading-card">
            <div className="dashboard-loading-content">
              <span className="result-spinner" aria-hidden="true" />
              <div>
                <h3>Salvando paciente</h3>
                <p>Atualizando o cadastro, aguarde.</p>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}

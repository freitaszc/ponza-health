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

const buildExcludedValue = (values) =>
  values
    .map((checked, index) => (checked ? null : index))
    .filter((item) => item !== null)
    .join(',')

export default function Result() {
  const { params } = useRouter()
  const currentPath = typeof window !== 'undefined' ? window.location.pathname : '/result'
  const initialCollapsed =
    typeof window !== 'undefined' && localStorage.getItem('dashboardSidebar') === '1'

  const token = useMemo(() => {
    if (typeof window === 'undefined') return ''
    return new URLSearchParams(window.location.search).get('token') || ''
  }, [])

  const [collapsed, setCollapsed] = useState(initialCollapsed)
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [prescriptionChecks, setPrescriptionChecks] = useState([])
  const [orientationChecks, setOrientationChecks] = useState([])
  const [prescriptionItems, setPrescriptionItems] = useState([])
  const [orientationItems, setOrientationItems] = useState([])
  const [newPrescription, setNewPrescription] = useState('')
  const [newOrientation, setNewOrientation] = useState('')
  const [patientDraft, setPatientDraft] = useState(null)
  const [summaryDraft, setSummaryDraft] = useState('')
  const [editModalOpen, setEditModalOpen] = useState(false)

  const sidebarNav = useMemo(() => navItems, [])

  useEffect(() => {
    let isMounted = true
    const fetchData = async () => {
      setLoading(true)
      setError('')

      const patientId = params?.patientId
      const endpoint = token
        ? `/api/lab_analysis/view?token=${encodeURIComponent(token)}`
        : patientId
          ? `/api/patient_result/${patientId}`
          : ''

      if (!endpoint) {
        setError('Resultado não encontrado.')
        setLoading(false)
        return
      }

      try {
        const response = await fetch(endpoint, { credentials: 'include' })
        const payload = await response.json().catch(() => ({}))
        if (!response.ok || payload.success === false) {
          throw new Error(payload.error || 'Não foi possível carregar o resultado.')
        }
        if (!isMounted) return
        setData(payload)
      } catch (err) {
        if (!isMounted) return
        const message = err instanceof Error ? err.message : 'Não foi possível carregar o resultado.'
        setError(message)
      } finally {
        if (!isMounted) return
        setLoading(false)
      }
    }

    fetchData()
    return () => {
      isMounted = false
    }
  }, [params?.patientId, token])

  useEffect(() => {
    if (!data || data.mode !== 'ai') return
    const prescriptions = Array.isArray(data.prescription) ? data.prescription : []
    const orientations = Array.isArray(data.orientations) ? data.orientations : []
    setPrescriptionItems(prescriptions)
    setOrientationItems(orientations)
    setPrescriptionChecks(prescriptions.map(() => true))
    setOrientationChecks(orientations.map(() => true))
    setPatientDraft(data.patient || {})
    setSummaryDraft(data.summary || '')
  }, [data])

  const toggleCheck = (setter, index) => {
    setter((prev) => prev.map((value, i) => (i === index ? !value : value)))
  }

  const handleAddPrescription = () => {
    const value = newPrescription.trim()
    if (!value) return
    setPrescriptionItems((prev) => [...prev, value])
    setPrescriptionChecks((prev) => [...prev, true])
    setNewPrescription('')
  }

  const handleAddOrientation = () => {
    const value = newOrientation.trim()
    if (!value) return
    setOrientationItems((prev) => [...prev, value])
    setOrientationChecks((prev) => [...prev, true])
    setNewOrientation('')
  }

  const updatePatientField = (key, value) => {
    setPatientDraft((prev) => ({ ...(prev || {}), [key]: value }))
  }

  const handleCancelEdit = () => {
    if (data?.mode === 'ai') {
      setPatientDraft(data.patient || {})
      setSummaryDraft(data.summary || '')
    }
    setEditModalOpen(false)
  }

  const handleSaveEdit = () => {
    setEditModalOpen(false)
  }

  const renderPatientDetails = () => {
    const patient = patientDraft || data?.patient || {}
    const details = [
      ['Nome', patient.nome],
      ['Data de nascimento', patient.data_nascimento],
      ['Sexo', patient.sexo],
      ['CPF', patient.cpf],
      ['Telefone', patient.telefone],
    ].filter(([, value]) => value)
    if (!details.length && data?.patient_details?.length) {
      return (
        <div className="result-grid">
          {data.patient_details.map((item, index) => (
            <div key={`${item.label}-${index}`}>
              <strong>{item.label}:</strong> {item.value}
            </div>
          ))}
        </div>
      )
    }
    if (!details.length) {
      return <div className="result-muted">Dados não informados.</div>
    }
    return (
      <div className="result-grid">
        {details.map(([label, value]) => (
          <div key={label}>
            <strong>{label}:</strong> {value}
          </div>
        ))}
      </div>
    )
  }

  const renderClassicPatient = () => {
    if (!data?.patient) return null
    const { name, birthdate, sex, cpf, phone_primary, phone_secondary } = data.patient
    const phoneLine = [phone_primary, phone_secondary].filter(Boolean).join(' / ')
    const details = [
      ['Nome', name],
      ['Data de nascimento', birthdate],
      ['Sexo', sex],
      ['CPF', cpf],
      ['Telefone', phoneLine],
    ].filter(([, value]) => value)
    if (!details.length) return null
    return (
      <div className="result-grid">
        {details.map(([label, value]) => (
          <div key={label}>
            <strong>{label}:</strong> {value}
          </div>
        ))}
      </div>
    )
  }

  const renderAiResults = () => {
    const exams = data?.exams || []
    const prescription = prescriptionItems
    const orientations = orientationItems

    return (
      <>
        <div className="result-section">
          <div className="result-section__header">
            <h3>Paciente</h3>
            <button type="button" className="result-edit" onClick={() => setEditModalOpen(true)}>
              Editar dados
            </button>
          </div>
          {renderPatientDetails()}
        </div>

        <div className="result-section">
          <h3>Resumo clínico</h3>
          <div className="result-textbox">{summaryDraft || 'Sem observações registradas.'}</div>
        </div>

        <div className="result-section">
          <h3>Resultados laboratoriais</h3>
          {exams.length ? (
            <div className="result-table">
              <table>
                <thead>
                  <tr>
                    <th>Exame</th>
                    <th>Valor</th>
                    <th>Referência</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {exams.map((exam, index) => {
                    const status = (exam.status || exam.estado || 'n/d').toString()
                    const statusKey = status.toLowerCase().replace(/[^a-z0-9]+/g, '-')
                    const label = exam.nome || exam.name || exam.test || '-'
                    const value = exam.valor || exam.value || '-'
                    return (
                      <tr key={`${label}-${index}`}>
                        <td>{label}</td>
                        <td>{value}</td>
                        <td>{exam.reference_display || exam.referencia || exam.reference || '-'}</td>
                        <td>
                          <span className={`lab-status lab-status--${statusKey}`}>{status}</span>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="result-textbox">Nenhum exame identificado.</div>
          )}
        </div>

        <div className="result-section">
          <h3>Prescrição</h3>
          <div className="result-add">
            <input
              type="text"
              className="lab-input"
              placeholder="Adicionar recomendação manual"
              value={newPrescription}
              onChange={(event) => setNewPrescription(event.target.value)}
            />
            <button type="button" className="lab-secondary" onClick={handleAddPrescription}>
              Adicionar
            </button>
          </div>
          {prescription.length ? (
            <div className="result-table">
              <table>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Recomendação</th>
                    <th>Incluir no PDF</th>
                  </tr>
                </thead>
                <tbody>
                  {prescription.map((item, index) => (
                    <tr key={`${item}-${index}`} className={!prescriptionChecks[index] ? 'is-excluded' : ''}>
                      <td>{index + 1}</td>
                      <td>{item}</td>
                      <td>
                        <label className="result-toggle">
                          <input
                            type="checkbox"
                            checked={prescriptionChecks[index] ?? true}
                            onChange={() => toggleCheck(setPrescriptionChecks, index)}
                          />
                          <span />
                        </label>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="result-textbox">Sem orientações de prescrição.</div>
          )}
        </div>

        <div className="result-section">
          <h3>Orientações</h3>
          <div className="result-add">
            <input
              type="text"
              className="lab-input"
              placeholder="Adicionar orientação manual"
              value={newOrientation}
              onChange={(event) => setNewOrientation(event.target.value)}
            />
            <button type="button" className="lab-secondary" onClick={handleAddOrientation}>
              Adicionar
            </button>
          </div>
          {orientations.length ? (
            <div className="result-orientations">
              {orientations.map((item, index) => (
                <div key={`${item}-${index}`} className={`result-orientation ${!orientationChecks[index] ? 'is-excluded' : ''}`}>
                  <span>{item}</span>
                  <label className="result-toggle">
                    <input
                      type="checkbox"
                      checked={orientationChecks[index] ?? true}
                      onChange={() => toggleCheck(setOrientationChecks, index)}
                    />
                    <span />
                  </label>
                </div>
              ))}
            </div>
          ) : (
            <div className="result-textbox">Sem orientações adicionais.</div>
          )}
        </div>
      </>
    )
  }

  const renderClassicResults = () => {
    const patientBlock = renderClassicPatient()
    return (
      <>
        {patientBlock ? (
          <div className="result-section">
            <h3>Paciente</h3>
            {patientBlock}
          </div>
        ) : null}

        <div className="result-section">
          <h3>Diagnóstico</h3>
          <div className="result-textbox">{data.diagnosis || 'Sem observações registradas.'}</div>
        </div>
        <div className="result-section">
          <h3>Prescrição</h3>
          <div className="result-textbox">{data.prescription || 'Sem recomendações registradas.'}</div>
        </div>
      </>
    )
  }

  const handleToggleSidebar = () => {
    const next = !collapsed
    setCollapsed(next)
    localStorage.setItem('dashboardSidebar', next ? '1' : '0')
  }

  const excludedPrescriptionsValue = buildExcludedValue(prescriptionChecks)
  const excludedOrientationsValue = buildExcludedValue(orientationChecks)
  const patientOverrideValue = patientDraft ? JSON.stringify(patientDraft) : ''
  const prescriptionOverrideValue = JSON.stringify(prescriptionItems || [])
  const orientationsOverrideValue = JSON.stringify(orientationItems || [])

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
          <header className="lab-hero lab-hero--result">
            <img src="/static/images/PonzaLab.svg" alt="Ponza Lab" className="lab-logo" />
            <h1 className="lab-title">Resultado da análise</h1>
            <p className="lab-subtitle">Veja o resumo e compartilhe o relatório com um clique.</p>
          </header>

          {loading ? (
            <div className="lab-panel result-loading">
              <span className="result-spinner" aria-hidden="true" />
              <span>Carregando resultado...</span>
            </div>
          ) : error ? (
            <div className="lab-alert">{error}</div>
          ) : (
            <div className="lab-panel">
              {data?.mode === 'ai' ? renderAiResults() : renderClassicResults()}

              <div className="lab-actions">
                {data?.mode === 'ai' ? (
                  <>
                    <form method="post" action={withBackend('/lab_analysis/pdf')} target="_blank">
                      <input type="hidden" name="token" value={data.pdf_token} />
                      <input type="hidden" name="patient_override" value={patientOverrideValue} />
                      <input type="hidden" name="summary_override" value={summaryDraft || ''} />
                      <input type="hidden" name="prescription_override" value={prescriptionOverrideValue} />
                      <input type="hidden" name="orientations_override" value={orientationsOverrideValue} />
                      <input type="hidden" name="excluded_prescriptions" value={excludedPrescriptionsValue} />
                      <input type="hidden" name="excluded_orientations" value={excludedOrientationsValue} />
                      <button type="submit" className="lab-primary">
                        Baixar PDF
                      </button>
                    </form>
                    <a className="lab-secondary" href="/upload">
                      Nova análise
                    </a>
                  </>
                ) : (
                  <>
                    <a className="lab-primary" href={withBackend(data.download_pdf_url)} target="_blank" rel="noreferrer">
                      Download PDF
                    </a>
                    <a className="lab-secondary" href="/upload">
                      Nova análise
                    </a>
                  </>
                )}
              </div>
            </div>
          )}
        </div>
      </main>

      {editModalOpen ? (
        <div className="lab-modal" role="dialog" aria-modal="true">
          <div className="lab-modal__card lab-modal__card--wide">
            <div className="lab-modal__badge">
              <i className="fa fa-pencil" aria-hidden="true" />
              <span>Editar resultado</span>
            </div>
            <h2>Atualize os dados do paciente</h2>
            <div className="result-edit-grid">
              <label className="lab-field">
                <span>Nome</span>
                <input
                  type="text"
                  className="lab-input"
                  value={patientDraft?.nome || ''}
                  onChange={(event) => updatePatientField('nome', event.target.value)}
                />
              </label>
              <label className="lab-field">
                <span>Data de nascimento</span>
                <input
                  type="text"
                  className="lab-input"
                  value={patientDraft?.data_nascimento || ''}
                  onChange={(event) => updatePatientField('data_nascimento', event.target.value)}
                />
              </label>
              <label className="lab-field">
                <span>Sexo</span>
                <input
                  type="text"
                  className="lab-input"
                  value={patientDraft?.sexo || ''}
                  onChange={(event) => updatePatientField('sexo', event.target.value)}
                />
              </label>
              <label className="lab-field">
                <span>CPF</span>
                <input
                  type="text"
                  className="lab-input"
                  value={patientDraft?.cpf || ''}
                  onChange={(event) => updatePatientField('cpf', event.target.value)}
                />
              </label>
              <label className="lab-field">
                <span>Telefone</span>
                <input
                  type="text"
                  className="lab-input"
                  value={patientDraft?.telefone || ''}
                  onChange={(event) => updatePatientField('telefone', event.target.value)}
                />
              </label>
              <label className="lab-field lab-field--full">
                <span>Resumo clínico</span>
                <textarea
                  rows={4}
                  className="lab-textarea"
                  value={summaryDraft}
                  onChange={(event) => setSummaryDraft(event.target.value)}
                />
              </label>
            </div>
            <div className="lab-modal__actions">
              <button type="button" className="btn-outline" onClick={handleCancelEdit}>
                Cancelar
              </button>
              <button type="button" className="btn-primary" onClick={handleSaveEdit}>
                Salvar alterações
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}

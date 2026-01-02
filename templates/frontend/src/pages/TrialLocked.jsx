import { useEffect, useState } from 'react'
import { useRouter } from '../components/Router'

const backendBase = import.meta.env.VITE_BACKEND_URL || ''
const withBackend = (path) => (backendBase ? `${backendBase}${path}` : path)

const resolvePlanUrl = (value, fallback) => {
  if (value) {
    if (/^https?:\/\//.test(value)) return value
    return withBackend(value)
  }
  return withBackend(fallback)
}

export default function TrialLocked() {
  const { navigate } = useRouter()
  const [loading, setLoading] = useState(true)
  const [status, setStatus] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    const load = async () => {
      setLoading(true)
      setError('')
      try {
        const response = await fetch('/api/trial_status', { credentials: 'include' })
        if (response.redirected && response.url.includes('/login')) {
          window.location.href = response.url
          return
        }
        const payload = await response.json().catch(() => null)
        if (!response.ok || !payload) {
          throw new Error('Não foi possível carregar o status do plano.')
        }
        if (!active) return
        setStatus(payload)
        if (!payload.trial_expired && (payload.plan_active || payload.trial_active)) {
          navigate('/index')
        }
      } catch (err) {
        if (!active) return
        setError('Não foi possível verificar o status do plano.')
      } finally {
        if (!active) return
        setLoading(false)
      }
    }
    load()
    return () => {
      active = false
    }
  }, [navigate])

  const trialLabel = status?.trial_expiration
    ? new Date(status.trial_expiration).toLocaleDateString('pt-BR')
    : null
  const monthlyUrl = resolvePlanUrl(status?.plans?.monthly, '/subscribe_pay_mensal')
  const yearlyUrl = resolvePlanUrl(status?.plans?.yearly, '/subscribe_pay_anual')

  return (
    <div className="trial-lock">
      <div className="trial-lock__card">
        <div className="trial-lock__badge">
          <i className="fa fa-lock" aria-hidden="true" />
          <span>Assinatura necessária</span>
        </div>
        <h1>Seu período de teste acabou</h1>
        <p>
          Para continuar usando o Ponza Health, escolha um plano mensal ou anual.
        </p>
        {trialLabel ? (
          <p className="trial-lock__meta">Expirou em {trialLabel}</p>
        ) : null}
        {error ? <div className="trial-lock__alert">{error}</div> : null}
        {loading ? (
          <div className="trial-lock__loading">Carregando opções...</div>
        ) : (
          <div className="trial-lock__plans">
            <div className="trial-lock__plan">
              <div>
                <h3>Plano mensal</h3>
                <p>Renovação automática, flexível para começar agora.</p>
              </div>
              <a className="btn-primary" href={monthlyUrl}>
                Assinar mensal
              </a>
            </div>
            <div className="trial-lock__plan trial-lock__plan--featured">
              <div>
                <h3>Plano anual</h3>
                <p>Economize no longo prazo e garanta acesso o ano todo.</p>
              </div>
              <a className="btn-outline" href={yearlyUrl}>
                Assinar anual
              </a>
            </div>
          </div>
        )}
        <div className="trial-lock__footer">
          Dúvidas sobre a assinatura? Entre em contato com nosso suporte.
        </div>
      </div>
    </div>
  )
}

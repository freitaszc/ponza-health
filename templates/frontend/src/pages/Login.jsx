import { useState } from 'react'
import { Link, useRouter } from '../components/Router'
import { buildCacheKey, writeCache } from '../utils/cache'

export default function Login() {
  const { navigate } = useRouter()
  const [error, setError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const dashboardCacheKey = buildCacheKey('dashboard', ['summary'])
  const patientsCacheKey = buildCacheKey('patients', ['all', 'all'])
  const quotesCacheKey = buildCacheKey('quotes', ['all'])
  const suppliersCacheKey = buildCacheKey('suppliers', ['all'])
  const stockCacheKey = buildCacheKey('stock', ['all', 'all'])

  const prefetchDashboard = async () => {
    try {
      const response = await fetch('/api/dashboard', { credentials: 'same-origin' })
      if (!response.ok) return
      const payload = await response.json().catch(() => null)
      if (!payload || typeof payload !== 'object') return
      writeCache(dashboardCacheKey, payload)
    } catch (err) {
      // ignore prefetch errors
    }
  }

  const prefetchPatients = async () => {
    try {
      const response = await fetch('/api/patients', { credentials: 'include' })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok || payload?.success === false) return
      const nextPatients = Array.isArray(payload?.patients) ? payload.patients : []
      writeCache(patientsCacheKey, nextPatients)
    } catch (err) {
      // ignore prefetch errors
    }
  }

  const prefetchQuotes = async () => {
    try {
      const response = await fetch('/api/quotes', { credentials: 'include' })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok || payload?.success === false) return
      const nextQuotes = Array.isArray(payload?.quotes) ? payload.quotes : []
      writeCache(quotesCacheKey, nextQuotes)
    } catch (err) {
      // ignore prefetch errors
    }
  }

  const prefetchSuppliers = async () => {
    try {
      const response = await fetch('/api/suppliers', { credentials: 'include' })
      const payload = await response.json().catch(() => null)
      if (!response.ok) return
      const nextSuppliers = Array.isArray(payload) ? payload : []
      writeCache(suppliersCacheKey, nextSuppliers)
    } catch (err) {
      // ignore prefetch errors
    }
  }

  const prefetchStock = async () => {
    try {
      const response = await fetch('/api/products', { credentials: 'same-origin' })
      if (!response.ok) return
      const payload = await response.json().catch(() => null)
      const nextProducts = Array.isArray(payload?.products) ? payload.products : []
      writeCache(stockCacheKey, {
        products: nextProducts,
        notifications_unread: payload?.notifications_unread || 0,
      })
    } catch (err) {
      // ignore prefetch errors
    }
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    setIsSubmitting(true)
    setError('')
    let shouldReset = true

    const form = event.currentTarget
    const payload = {
      login: form.login.value.trim(),
      password: form.password.value,
    }

    try {
      const response = await fetch('/api/login', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },
        body: JSON.stringify(payload),
      })

      const data = await response.json().catch(() => ({}))
      if (!response.ok || data.success === false) {
        setError(data.error || 'Não foi possível entrar. Verifique suas credenciais.')
        return
      }

      const redirectTarget = data.redirect || '/index'
      const isDashboardTarget = redirectTarget === '/index' || redirectTarget.startsWith('/index?')
      const isExternal = /^(https?:)?\/\//.test(redirectTarget)

      if (isDashboardTarget) {
        const dashboardPrefetch = prefetchDashboard()
        void prefetchPatients()
        void prefetchQuotes()
        void prefetchSuppliers()
        void prefetchStock()
        await dashboardPrefetch
      } else {
        void prefetchDashboard()
        void prefetchPatients()
        void prefetchQuotes()
        void prefetchSuppliers()
        void prefetchStock()
      }

      if (isExternal) {
        shouldReset = false
        window.location.href = redirectTarget
      } else {
        shouldReset = false
        navigate(redirectTarget)
      }
    } catch (err) {
      setError('Não foi possível conectar ao servidor. Tente novamente.')
    } finally {
      if (shouldReset) {
        setIsSubmitting(false)
      }
    }
  }

  return (
    <section className="section auth-page">
      <div className="container auth-layout">
        <div className="auth-card auth-card--center">
          <div className="auth-card-head">
            <h2>Entrar</h2>
          </div>

          {error ? (
            <div className="auth-message auth-message--error" role="alert">
              {error}
            </div>
          ) : null}

          <form className="auth-form" onSubmit={handleSubmit}>
            <label>
              Usuário ou e-mail
              <input type="text" name="login" required />
            </label>
            <label>
              Senha
              <input type="password" name="password" required />
            </label>
            <div className="auth-helper">
              <Link className="link-inline" to="/forgot_password">
                Esqueceu a senha?
              </Link>
            </div>
            <div className="auth-actions">
              <button className="btn-primary btn-auth" type="submit" disabled={isSubmitting}>
                {isSubmitting ? (
                  <>
                    <span className="btn-spinner" />
                    Entrando...
                  </>
                ) : (
                  'Entrar'
                )}
              </button>
            </div>
          </form>
        </div>
      </div>
    </section>
  )
}

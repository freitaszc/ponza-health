import { useState } from 'react'
import { Link } from '../components/Router'

export default function Login() {
  const [error, setError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  const handleSubmit = async (event) => {
    event.preventDefault()
    setIsSubmitting(true)
    setError('')

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

      window.location.href = data.redirect || '/index'
    } catch (err) {
      setError('Não foi possível conectar ao servidor. Tente novamente.')
    } finally {
      setIsSubmitting(false)
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
              <input type="text" name="login" placeholder="usuario ou contato@ponza.health" required />
            </label>
            <label>
              Senha
              <input type="password" name="password" placeholder="••••••••" required />
            </label>
            <div className="auth-helper">
              <Link className="link-inline" to="/forgot_password">
                Esqueceu a senha?
              </Link>
            </div>
            <div className="auth-actions">
              <button className="btn-primary btn-auth" type="submit" disabled={isSubmitting}>
                Entrar
              </button>
            </div>
          </form>
        </div>
      </div>
    </section>
  )
}

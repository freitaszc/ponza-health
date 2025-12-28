import { useState } from 'react'

export default function ForgotPassword() {
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  const handleSubmit = async (event) => {
    event.preventDefault()
    setError('')
    setSuccess('')
    setIsSubmitting(true)

    const form = event.currentTarget
    const payload = { email: form.email.value.trim() }

    try {
      const response = await fetch('/forgot_password', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },
        body: JSON.stringify(payload),
      })

      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        setError(data.error || 'Não foi possível enviar o link. Tente novamente.')
        return
      }

      setSuccess('Se este e-mail existir, enviaremos um link de recuperação.')
      form.reset()
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
            <h2>Recuperar senha</h2>
            <p>Informe seu e-mail para receber o link de redefinição.</p>
          </div>

          {error ? (
            <div className="auth-message auth-message--error" role="alert">
              {error}
            </div>
          ) : null}
          {success ? (
            <div className="auth-message auth-message--success" role="status">
              {success}
            </div>
          ) : null}

          <form className="auth-form" onSubmit={handleSubmit}>
            <label>
              E-mail
              <input type="email" name="email" placeholder="contato@ponza.health" required />
            </label>
            <div className="auth-actions">
              <button className="btn-primary btn-auth" type="submit" disabled={isSubmitting}>
                Enviar link
              </button>
            </div>
            <div className="auth-helper">
              <a className="link-inline" href="/login">
                Voltar ao login
              </a>
            </div>
          </form>
        </div>
      </div>
    </section>
  )
}

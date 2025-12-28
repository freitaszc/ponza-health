import { useState } from 'react'
import { useRouter } from '../components/Router'

export default function ResetPassword() {
  const { params } = useRouter()
  const token = params?.token
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  const handleSubmit = async (event) => {
    event.preventDefault()
    setError('')
    setSuccess('')
    setIsSubmitting(true)

    const form = event.currentTarget
    const payload = {
      password: form.password.value,
      confirm: form.confirm.value,
    }

    try {
      const response = await fetch(`/reset_password/${token}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },
        body: JSON.stringify(payload),
      })

      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        const fallback =
          data.error === 'password_mismatch'
            ? 'As senhas não coincidem.'
            : data.error === 'password_too_short'
              ? 'Informe uma senha com pelo menos 6 caracteres.'
              : data.error === 'invalid_token'
                ? 'Este link de redefinição não é válido ou expirou.'
                : data.error === 'user_not_found'
                  ? 'Usuário não encontrado.'
              : 'Não foi possível atualizar a senha.'
        setError(fallback)
        return
      }

      setSuccess('Senha alterada com sucesso. Faça login.')
      form.reset()
    } catch (err) {
      setError('Não foi possível conectar ao servidor. Tente novamente.')
    } finally {
      setIsSubmitting(false)
    }
  }

  if (!token) {
    return (
      <section className="section auth-page">
        <div className="container auth-layout">
          <div className="auth-card auth-card--center">
            <div className="auth-card-head">
              <h2>Link inválido</h2>
            </div>
            <p className="auth-message auth-message--error">Este link de redefinição não é válido.</p>
            <div className="auth-actions">
              <a className="btn-primary btn-auth" href="/forgot_password">
                Solicitar novo link
              </a>
            </div>
          </div>
        </div>
      </section>
    )
  }

  return (
    <section className="section auth-page">
      <div className="container auth-layout">
        <div className="auth-card auth-card--center">
          <div className="auth-card-head">
            <h2>Nova senha</h2>
            <p>Defina sua nova senha para continuar.</p>
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
              Nova senha
              <input type="password" name="password" placeholder="••••••••" required minLength={6} />
            </label>
            <label>
              Confirmar senha
              <input type="password" name="confirm" placeholder="••••••••" required minLength={6} />
            </label>
            <div className="auth-actions">
              <button className="btn-primary btn-auth" type="submit" disabled={isSubmitting}>
                Atualizar senha
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

import { useState } from 'react'
import { useRouter } from '../components/Router'

export default function Cadastro() {
  const { navigate } = useRouter()
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  const handleSubmit = async (event) => {
    event.preventDefault()
    setIsSubmitting(true)
    setError('')
    setSuccess('')

    const form = event.currentTarget
    const payload = {
      username: form.username.value.trim(),
      email: form.email.value.trim(),
      password: form.password.value,
      confirm: form.confirm.value,
      plan: form.plan.value || '',
    }

    try {
      const response = await fetch('/api/register', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },
        body: JSON.stringify(payload),
      })

      const data = await response.json().catch(() => ({}))
      if (!response.ok || data.success === false) {
        setError(data.error || 'Não foi possível criar sua conta. Revise os dados e tente novamente.')
        return
      }

      setSuccess(
        data.message ||
          'Conta criada com sucesso. Enviamos um link de confirmação no seu e-mail para liberar o acesso.',
      )
      if (data.redirect) {
        setTimeout(() => navigate(data.redirect), 1500)
      }
    } catch (err) {
      setError('Não foi possível conectar ao servidor. Tente novamente.')
    } finally {
      setIsSubmitting(false)
    }
  }
  const planParam =
    typeof window !== 'undefined' ? new URLSearchParams(window.location.search).get('plan') : null
  const normalizedPlan = planParam ? planParam.toLowerCase() : ''
  const planMap = {
    mensal: 'monthly',
    anual: 'yearly',
    monthly: 'monthly',
    yearly: 'yearly',
  }
  const selectedPlan = planMap[normalizedPlan] ?? ''

  return (
    <section className="section auth-page alt">
      <div className="container auth-layout">
        <div className="auth-card auth-card--center">
          <div className="auth-card-head">
            <h2>Criar conta</h2>
            <img src="/static/images/6.svg" alt="Ponza Health" />
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
              Nome de usuário
              <input type="text" name="username" placeholder="Seu usuário" required />
            </label>
            <label>
              E-mail
              <input type="email" name="email" placeholder="nome@empresa.com" required />
            </label>
            <label>
              Senha
              <input type="password" name="password" required />
            </label>
            <label>
              Confirmar senha
              <input type="password" name="confirm" required />
            </label>
            <label>
              Plano
              <select name="plan" defaultValue={selectedPlan}>
                <option value="">Teste gratuito</option>
                <option value="monthly">Plano mensal</option>
                <option value="yearly">Plano anual</option>
              </select>
            </label>
            <div className="auth-actions">
              <button className="btn-primary btn-auth" type="submit" disabled={isSubmitting}>
                Criar conta
              </button>
            </div>
          </form>
        </div>
      </div>
    </section>
  )
}

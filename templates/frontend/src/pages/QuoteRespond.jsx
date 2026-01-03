import { useEffect, useMemo, useState } from 'react'
import { useRouter } from '../components/Router'

const buildPrefill = (items, prefill) =>
  items.map((_, idx) => ({
    price: prefill?.[idx]?.price || '',
    deadline: prefill?.[idx]?.deadline || '',
  }))

export default function QuoteRespond() {
  const { params } = useRouter()
  const token = params?.token
  const [data, setData] = useState(null)
  const [answers, setAnswers] = useState([])
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    let mounted = true
    const load = async () => {
      if (!token) {
        setLoading(false)
        return
      }
      setError('')
      try {
        const res = await fetch(`/quotes/respond/${token}`, {
          headers: { Accept: 'application/json' },
        })
        const payload = await res.json().catch(() => null)
        if (!res.ok && res.status !== 410) {
          throw new Error(payload?.error || 'Não foi possível carregar a cotação.')
        }
        if (mounted) {
          setData(payload)
          setAnswers(buildPrefill(payload?.items || [], payload?.prefill || []))
        }
      } catch (err) {
        if (mounted) {
          setError(err.message || 'Não foi possível carregar a cotação.')
        }
      } finally {
        if (mounted) {
          setLoading(false)
        }
      }
    }
    load()
    return () => {
      mounted = false
    }
  }, [token])

  const subtitle = useMemo(() => {
    if (!data) return ''
    return `${data.clinic_name || 'Equipe Ponza Health'} convidou você para informar preços e prazos.`
  }, [data])

  const updateAnswer = (index, field, value) => {
    setAnswers((prev) => {
      const next = [...prev]
      next[index] = { ...(next[index] || {}), [field]: value }
      return next
    })
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    if (!token || submitting) return
    setError('')
    setSuccess('')
    setSubmitting(true)
    try {
      const res = await fetch(`/quotes/respond/${token}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ answers }),
      })
      const payload = await res.json().catch(() => ({}))
      if (!res.ok || payload?.success === false) {
        throw new Error(payload?.message || 'Não foi possível enviar a resposta.')
      }
      setSuccess('Resposta enviada com sucesso. Obrigado!')
      setData((prev) => (prev ? { ...prev, submitted: true } : prev))
    } catch (err) {
      setError(err.message || 'Não foi possível enviar a resposta.')
    } finally {
      setSubmitting(false)
    }
  }

  if (!token) {
    return (
      <section className="quote-public">
        <div className="quote-public-card">
          <div className="quote-public-top">
            <img src="/static/images/15.svg" alt="Ponza Health" className="quote-public-top-logo" />
            <span className="quote-public-top-tag">Portal de cotação</span>
          </div>
          <h1>Link inválido</h1>
          <p className="quote-public-subtitle">Este link de cotação não é válido.</p>
        </div>
      </section>
    )
  }

  return (
    <section className="quote-public">
      <div className="quote-public-card">
        <div className="quote-public-top">
          <img src="/static/images/15.svg" alt="Ponza Health" className="quote-public-top-logo" />
          <span className="quote-public-top-tag">Portal de cotação</span>
        </div>

        <header className="quote-public-header">
          <div className="quote-public-title">
            <p className="quote-public-kicker">Cotação</p>
            <h1>Responder cotação</h1>
            <p className="quote-public-subtitle">{subtitle}</p>
          </div>
          <div className="quote-public-clinic">
            <span className="quote-public-clinic-label">Clínica solicitante</span>
            <strong>{data?.clinic_name || 'Equipe Ponza Health'}</strong>
            {data?.clinic_address ? (
              <span className="quote-public-address">{data.clinic_address}</span>
            ) : null}
          </div>
        </header>

        <div className="quote-public-supplier">
          <div>
            <span>Fornecedor</span>
            <strong>{data?.supplier?.name || '-'}</strong>
          </div>
          <span className="quote-public-chip">Link exclusivo</span>
        </div>
        <p className="quote-public-hint">
          Este link é exclusivo para este fornecedor. Se precisar ajustar valores, basta editar e reenviar.
        </p>

        {loading ? <div className="quote-public-status">Carregando...</div> : null}
        {error ? <div className="quote-public-status is-error">{error}</div> : null}
        {success ? <div className="quote-public-status">{success}</div> : null}
        {data?.submitted ? (
          <div className="quote-public-status">
            Você já enviou uma resposta. Ajuste os valores e envie novamente se precisar.
          </div>
        ) : null}

        {data?.expired ? (
          <div className="quote-public-status is-error">Este link expirou. Solicite um novo link à clínica.</div>
        ) : null}

        {!data?.expired && data?.items?.length ? (
          <form className="quote-public-form" onSubmit={handleSubmit}>
            <div className="quote-public-response">
              <div className="quote-public-response-head">
                <div>
                  <h2>Itens da cotação</h2>
                  <p>Preencha o preço e o prazo para cada produto indicado pela clínica.</p>
                </div>
                <span className="quote-public-count">{data.items.length} itens</span>
              </div>
              <div className="quote-public-table">
                <table>
                  <thead>
                    <tr>
                      <th>Item</th>
                      <th>Preço unitário</th>
                      <th>Prazo (dias)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.items.map((item, index) => (
                      <tr key={`${item}-${index}`}>
                        <td>
                          <div className="quote-public-item">
                            <span className="quote-public-index">{index + 1}</span>
                            <span className="quote-public-item-name">{item}</span>
                          </div>
                        </td>
                        <td>
                          <div className="quote-input">
                            <span>R$</span>
                            <input
                              type="text"
                              name={`price_${index}`}
                              inputMode="decimal"
                              placeholder="Ex: 125,90"
                              aria-label={`Preço do item ${item}`}
                              value={answers[index]?.price || ''}
                              onChange={(e) => updateAnswer(index, 'price', e.target.value)}
                            />
                          </div>
                        </td>
                        <td>
                          <div className="quote-input quote-input--compact">
                            <input
                              type="number"
                              name={`deadline_${index}`}
                              min="0"
                              step="1"
                              placeholder="Ex: 5"
                              aria-label={`Prazo em dias do item ${item}`}
                              value={answers[index]?.deadline || ''}
                              onChange={(e) => updateAnswer(index, 'deadline', e.target.value)}
                            />
                            <span>dias</span>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="quote-public-actions">
              <button type="submit" disabled={submitting}>
                {submitting ? 'Enviando...' : data?.submitted ? 'Atualizar resposta' : 'Enviar resposta'}
              </button>
            </div>
          </form>
        ) : null}

        {!data?.expired && data && !data?.items?.length ? (
          <div className="quote-public-status is-error">
            Esta cotação não possui itens cadastrados. Entre em contato com a clínica.
          </div>
        ) : null}
      </div>
    </section>
  )
}

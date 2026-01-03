import { useEffect, useRef, useState } from 'react'

const defaultSteps = [
  { id: 'upload', label: 'Recebendo o envio' },
  { id: 'extract', label: 'Extraindo dados do PDF' },
  { id: 'ocr', label: 'OCR quando necessário' },
  { id: 'openai', label: 'Analisando com IA' },
  { id: 'postprocess', label: 'Organizando resultados' },
  { id: 'db_save', label: 'Salvando no sistema' },
]

const normalizeOrigin = () =>
  typeof window !== 'undefined' ? window.location.origin : ''

const parseSseEvent = (chunk) => {
  const lines = chunk.split('\n')
  let event = 'message'
  const dataLines = []
  for (const line of lines) {
    if (line.startsWith('event:')) {
      event = line.replace('event:', '').trim()
      continue
    }
    if (line.startsWith('data:')) {
      dataLines.push(line.replace('data:', '').trim())
    }
  }
  const dataText = dataLines.join('\n')
  if (!dataText) return { event, data: null }
  try {
    return { event, data: JSON.parse(dataText) }
  } catch (err) {
    return { event, data: { message: dataText } }
  }
}

export default function LabAnalysisLoading() {
  const [status, setStatus] = useState('Aguardando envio do arquivo...')
  const [currentStep, setCurrentStep] = useState('')
  const [error, setError] = useState('')
  const [timings, setTimings] = useState(null)
  const analysisStartedRef = useRef(false)

  useEffect(() => {
    if (typeof window === 'undefined') return undefined
    const opener = window.opener
    if (opener) {
      opener.postMessage({ type: 'ponza_lab_ready' }, normalizeOrigin())
    }

    const handleMessage = (event) => {
      if (event.origin !== window.location.origin) return
      const { type, payload } = event.data || {}
      if (type === 'ponza_lab_start' && payload && !analysisStartedRef.current) {
        analysisStartedRef.current = true
        startAnalysis(payload)
      }
    }

    window.addEventListener('message', handleMessage)
    return () => window.removeEventListener('message', handleMessage)
  }, [])

  const startAnalysis = async (payloadEntries) => {
    const formData = new FormData()
    payloadEntries.forEach(([key, value]) => {
      formData.append(key, value)
    })
    formData.append('stream', '1')

    setStatus('Preparando analise...')
    setCurrentStep('upload')
    setError('')

    try {
      const response = await fetch('/api/upload', {
        method: 'POST',
        body: formData,
        credentials: 'include',
        headers: {
          Accept: 'text/event-stream',
        },
      })

      const contentType = response.headers.get('content-type') || ''
      if (!contentType.includes('text/event-stream') || !response.body) {
        const payload = await response.json().catch(() => null)
        if (!response.ok || !payload?.success) {
          throw new Error(payload?.error || 'Nao foi possivel iniciar a analise.')
        }
        if (payload.redirect_url) {
          window.location.href = payload.redirect_url
          if (window.opener) {
            window.opener.postMessage(
              { type: 'ponza_lab_done', redirectUrl: payload.redirect_url },
              normalizeOrigin(),
            )
          }
          return
        }
        throw new Error('Resposta invalida do servidor.')
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop() || ''
        parts.forEach((part) => {
          const { event, data } = parseSseEvent(part)
          if (!data) return
          if (event === 'status') {
            setStatus(data.message || 'Processando...')
            if (data.step) {
              setCurrentStep(data.step)
            }
          }
          if (event === 'error') {
            setError(data.error || 'Erro ao processar o envio.')
            setStatus('')
            if (window.opener) {
              window.opener.postMessage(
                { type: 'ponza_lab_error', error: data.error },
                normalizeOrigin(),
              )
            }
          }
          if (event === 'done') {
            if (data.timings) {
              setTimings(data.timings)
            }
            setCurrentStep('db_save')
            if (data.redirect_url) {
              if (window.opener) {
                window.opener.postMessage(
                  { type: 'ponza_lab_done', redirectUrl: data.redirect_url },
                  normalizeOrigin(),
                )
              }
              window.location.href = data.redirect_url
            }
          }
        })
      }
    } catch (err) {
      const message = err?.message || 'Nao foi possivel iniciar a analise.'
      setError(message)
      setStatus('')
      if (window.opener) {
        window.opener.postMessage({ type: 'ponza_lab_error', error: message }, normalizeOrigin())
      }
    }
  }

  return (
    <div className="lab-loading">
      <div className="lab-loading__card">
        <div className="lab-loading__badge">
          <i className="fa fa-flask" aria-hidden="true" />
          <span>Ponza Lab</span>
        </div>
        <h1>Análise em andamento</h1>
        <p>
          {error || status || 'Aguardando o envio do exame para iniciar a análise.'}
        </p>
        {!error ? (
          <div className="loading-dots" aria-label="Carregando">
            <span />
            <span />
            <span />
          </div>
        ) : null}
        <div className="lab-loading__steps">
          {defaultSteps.map((step) => (
            <div
              key={step.id}
              className={`lab-loading__step ${currentStep === step.id ? 'is-active' : ''}`}
            >
              <span>{step.label}</span>
            </div>
          ))}
        </div>
        {timings ? (
          <div className="lab-loading__timings">
            <strong>Tempo de cada etapa (ms)</strong>
            <div>
              {Object.entries(timings).map(([key, value]) => (
                <span key={key}>
                  {key}: {value}
                </span>
              ))}
            </div>
          </div>
        ) : null}
        <div className="lab-loading__footer">
          Esta aba ficará aberta até o resultado finalizar.
        </div>
      </div>
    </div>
  )
}

import { useCallback, useEffect, useMemo, useState } from 'react'
import { buildCacheKey, readCache, writeCache } from '../utils/cache'

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

const formatCurrency = (value) =>
  new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL', minimumFractionDigits: 2 }).format(
    Number(value) || 0,
  )

const padTwo = (value) => String(value).padStart(2, '0')
const formatDateParts = (date) => `${padTwo(date.getDate())}/${padTwo(date.getMonth() + 1)}/${date.getFullYear()}`

const formatDate = (dateStr) => {
  if (!dateStr) return '—'
  const d = new Date(dateStr)
  if (Number.isNaN(d.getTime())) return '—'
  return formatDateParts(d)
}

const formatDateTime = (dateStr) => {
  if (!dateStr) return '—'
  const d = new Date(dateStr)
  if (Number.isNaN(d.getTime())) return '—'
  return `${formatDateParts(d)} ${padTwo(d.getHours())}:${padTwo(d.getMinutes())}`
}

// Multi-bar chart component for income vs expenses
const MultiBarChart = ({ data }) => {
  const maxValue = Math.max(...data.flatMap(item => [item.income || 0, item.expense || 0]), 1)
  return (
    <div className="finance-multi-bars">
      {data.map((item) => (
        <div key={item.month} className="finance-multi-bar">
          <div className="finance-multi-bar__container">
            <div
              className="finance-multi-bar__fill finance-multi-bar__fill--income"
              style={{ height: `${((item.income || 0) / maxValue) * 100}%` }}
              title={`Entradas: ${formatCurrency(item.income)}`}
            />
            <div
              className="finance-multi-bar__fill finance-multi-bar__fill--expense"
              style={{ height: `${((item.expense || 0) / maxValue) * 100}%` }}
              title={`Saídas: ${formatCurrency(item.expense)}`}
            />
          </div>
          <span className="finance-multi-bar__label">{item.month}</span>
        </div>
      ))}
    </div>
  )
}

// Payment method labels in Portuguese
const paymentMethodLabels = {
  'pix': 'PIX',
  'cash': 'Dinheiro',
  'credit_card': 'Cartão de Crédito',
  'debit_card': 'Cartão de Débito',
  'transfer': 'Transferência',
  'check': 'Cheque',
  'insurance': 'Convênio'
}

// Payment method breakdown component
const PaymentMethodBreakdown = ({ methods }) => {
  const total = Object.values(methods).reduce((sum, val) => sum + val, 0)
  if (total === 0) return <p className="finance-empty">Nenhum dado de pagamento</p>
  
  const colors = ['#0f63ff', '#10b981', '#f59e0b', '#6366f1', '#ec4899', '#14b8a6', '#8b5cf6']
  
  return (
    <div className="payment-method-breakdown">
      {Object.entries(methods).map(([method, value], idx) => {
        const pct = ((value / total) * 100).toFixed(1)
        return (
          <div key={method} className="payment-method-item">
            <div className="payment-method-bar">
              <div 
                className="payment-method-bar__fill" 
                style={{ width: `${pct}%`, backgroundColor: colors[idx % colors.length] }}
              />
            </div>
            <div className="payment-method-info">
              <span className="payment-method-label">{paymentMethodLabels[method] || method}</span>
              <span className="payment-method-value">{formatCurrency(value)} ({pct}%)</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

// Modal component
const Modal = ({ isOpen, onClose, title, children, zIndex }) => {
  if (!isOpen) return null
  
  return (
    <div className="modal-overlay" onClick={onClose} style={zIndex ? { zIndex } : undefined}>
      <div className="modal-content modal-content--finance" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h2>{title}</h2>
          <button type="button" className="modal-close" onClick={onClose}>
            <i className="fa fa-times" />
          </button>
        </div>
        <div className="modal-body">
          {children}
        </div>
      </div>
    </div>
  )
}

export default function Finances() {
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('dashboardSidebar') === '1')
  const [activeTab, setActiveTab] = useState('overview')
  const [cashboxFilter, setCashboxFilter] = useState('all')
  const [paymentFilter, setPaymentFilter] = useState('all')
  const [timeframe, setTimeframe] = useState('30d')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  
  // Data states
  const [summary, setSummary] = useState(null)
  const [monthlyData, setMonthlyData] = useState([])
  const [paymentMethods, setPaymentMethods] = useState({})
  const [cashboxes, setCashboxes] = useState([])
  const [payments, setPayments] = useState([])
  const [patients, setPatients] = useState([])
  
  // Modal states
  const [showNewCashbox, setShowNewCashbox] = useState(false)
  const [showNewPayment, setShowNewPayment] = useState(false)
  const [showTransaction, setShowTransaction] = useState(null)
  const [showReceivePayment, setShowReceivePayment] = useState(null)
  const [showCashboxDetail, setShowCashboxDetail] = useState(null)
  const [cashboxTransactions, setCashboxTransactions] = useState([])
  
  // Form states
  const [newCashboxForm, setNewCashboxForm] = useState({ name: '', description: '', initial_balance: 0, responsible: '' })
  const [newPaymentForm, setNewPaymentForm] = useState({ patient_id: '', amount: '', description: '', payment_type: 'consultation', due_date: '' })
  const [transactionForm, setTransactionForm] = useState({ type: 'income', amount: '', category: '', description: '', payment_method: 'cash' })
  const [receiveForm, setReceiveForm] = useState({ amount: '', payment_method: 'cash', cashbox_id: '' })

  const sidebarNav = useMemo(() => navItems, [])
  const isActiveLink = (href) => {
    const resolved = resolvePath(href)
    const current = window.location.pathname.replace(/\/$/, '') || '/'
    if (resolved === '/quotes') return current.startsWith('/quotes')
    return current === resolved
  }

  // Fetch financial summary
  const fetchSummary = useCallback(async () => {
    try {
      const res = await fetch(withBackend(`/api/finances/summary?timeframe=${timeframe}`), { credentials: 'include' })
      const data = await res.json()
      if (data.success) {
        setSummary(data.summary)
        setMonthlyData(data.monthly_data || [])
        setPaymentMethods(data.payment_methods || {})
      }
    } catch (err) {
      console.error('Error fetching summary:', err)
    }
  }, [timeframe])

  // Fetch cashboxes
  const fetchCashboxes = useCallback(async () => {
    try {
      const res = await fetch(withBackend(`/api/cashboxes?status=${cashboxFilter}`), { credentials: 'include' })
      const data = await res.json()
      if (data.success) {
        setCashboxes(data.cashboxes || [])
      }
    } catch (err) {
      console.error('Error fetching cashboxes:', err)
    }
  }, [cashboxFilter])

  // Fetch patient payments
  const fetchPayments = useCallback(async () => {
    try {
      const res = await fetch(withBackend(`/api/patient_payments?status=${paymentFilter}`), { credentials: 'include' })
      const data = await res.json()
      if (data.success) {
        setPayments(data.payments || [])
      }
    } catch (err) {
      console.error('Error fetching payments:', err)
    }
  }, [paymentFilter])

  // Fetch patients for dropdown
  const fetchPatients = useCallback(async () => {
    try {
      const res = await fetch(withBackend('/api/patients'), { credentials: 'include' })
      const data = await res.json()
      // API returns { patients: [...], total: N } without success flag
      if (data.patients) {
        setPatients(data.patients || [])
      }
    } catch (err) {
      console.error('Error fetching patients:', err)
    }
  }, [])

  // Fetch cashbox details
  const fetchCashboxDetail = useCallback(async (cashboxId) => {
    try {
      const res = await fetch(withBackend(`/api/cashboxes/${cashboxId}`), { credentials: 'include' })
      const data = await res.json()
      if (data.success) {
        setShowCashboxDetail(data.cashbox)
        setCashboxTransactions(data.transactions || [])
      }
    } catch (err) {
      console.error('Error fetching cashbox detail:', err)
    }
  }, [])

  // Initial load
  useEffect(() => {
    const loadData = async () => {
      setLoading(true)
      await Promise.all([
        fetchSummary(),
        fetchCashboxes(),
        fetchPayments(),
        fetchPatients()
      ])
      setLoading(false)
    }
    loadData()
  }, [])

  // Refetch data when page becomes visible (e.g., after editing patient in another tab)
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        fetchPayments()
        fetchPatients()
      }
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange)
  }, [fetchPayments, fetchPatients])

  // Reload on filter changes
  useEffect(() => { fetchSummary() }, [timeframe])
  useEffect(() => { fetchCashboxes() }, [cashboxFilter])
  useEffect(() => { fetchPayments() }, [paymentFilter])

  // Create new cashbox
  const handleCreateCashbox = async (e) => {
    e.preventDefault()
    try {
      const res = await fetch(withBackend('/api/cashboxes'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(newCashboxForm)
      })
      const data = await res.json()
      if (data.success) {
        setShowNewCashbox(false)
        setNewCashboxForm({ name: '', description: '', initial_balance: 0, responsible: '' })
        fetchCashboxes()
        fetchSummary()
      } else {
        alert(data.error || 'Erro ao criar caixa')
      }
    } catch (err) {
      alert('Erro ao criar caixa')
    }
  }

  // Close/reopen cashbox
  const handleCashboxAction = async (cashboxId, action) => {
    try {
      const res = await fetch(withBackend(`/api/cashboxes/${cashboxId}`), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ action })
      })
      const data = await res.json()
      if (data.success) {
        fetchCashboxes()
        fetchSummary()
        if (showCashboxDetail) {
          fetchCashboxDetail(cashboxId)
        }
      } else {
        alert(data.error || 'Erro na operação')
      }
    } catch (err) {
      alert('Erro na operação')
    }
  }

  // Add transaction to cashbox
  const handleAddTransaction = async (e) => {
    e.preventDefault()
    if (!showTransaction) return
    
    try {
      const res = await fetch(withBackend(`/api/cashboxes/${showTransaction.id}/transactions`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(transactionForm)
      })
      const data = await res.json()
      if (data.success) {
        setShowTransaction(null)
        setTransactionForm({ type: 'income', amount: '', category: '', description: '', payment_method: 'cash' })
        fetchCashboxes()
        fetchSummary()
        if (showCashboxDetail) {
          fetchCashboxDetail(showCashboxDetail.id)
        }
      } else {
        alert(data.error || 'Erro ao adicionar transação')
      }
    } catch (err) {
      alert('Erro ao adicionar transação')
    }
  }

  // Create patient payment
  const handleCreatePayment = async (e) => {
    e.preventDefault()
    try {
      const res = await fetch(withBackend('/api/patient_payments'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(newPaymentForm)
      })
      const data = await res.json()
      if (data.success) {
        setShowNewPayment(false)
        setNewPaymentForm({ patient_id: '', amount: '', description: '', payment_type: 'consultation', due_date: '' })
        fetchPayments()
        fetchSummary()
      } else {
        alert(data.error || 'Erro ao criar cobrança')
      }
    } catch (err) {
      alert('Erro ao criar cobrança')
    }
  }

  // Receive payment
  const handleReceivePayment = async (e) => {
    e.preventDefault()
    if (!showReceivePayment) return
    
    try {
      const res = await fetch(withBackend(`/api/patient_payments/${showReceivePayment.id}`), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          action: 'receive',
          amount: parseFloat(receiveForm.amount),
          payment_method: receiveForm.payment_method,
          cashbox_id: receiveForm.cashbox_id || null
        })
      })
      const data = await res.json()
      if (data.success) {
        setShowReceivePayment(null)
        setReceiveForm({ amount: '', payment_method: 'cash', cashbox_id: '' })
        fetchPayments()
        fetchCashboxes()
        fetchSummary()
      } else {
        alert(data.error || 'Erro ao receber pagamento')
      }
    } catch (err) {
      alert('Erro ao receber pagamento')
    }
  }

  // Open cashboxes for receiving payments
  const openCashboxes = cashboxes.filter(c => c.status === 'open')

  const statusBadge = (status) => {
    const map = {
      'pending': { label: 'Pendente', cls: 'tag--warn' },
      'partial': { label: 'Parcial', cls: 'tag--info' },
      'paid': { label: 'Pago', cls: 'tag--success' },
      'cancelled': { label: 'Cancelado', cls: 'tag--neutral' },
      'open': { label: 'Aberto', cls: 'tag--success' },
      'closed': { label: 'Fechado', cls: 'tag--neutral' }
    }
    const s = map[status] || { label: status, cls: 'tag--neutral' }
    return <span className={`tag ${s.cls}`}>{s.label}</span>
  }

  if (loading) {
    return (
      <div className={`dashboard-shell ${collapsed ? 'is-collapsed' : ''}`}>
        <aside className="dashboard-sidebar">
          <div className="dashboard-sidebar__brand">
            <div className="dashboard-logo-wrap">
              <img src="/static/images/5.svg" alt="Ponza Health" className="dashboard-logo dashboard-logo--full" />
              <img src="/static/images/15.svg" alt="Ponza Health" className="dashboard-logo dashboard-logo--compact" />
            </div>
          </div>
          <nav className="dashboard-nav" aria-label="Menu principal">
            {sidebarNav.map((item) => (
              <a key={item.href} className={`dashboard-link ${isActiveLink(item.href) ? 'is-active' : ''}`} href={withBackend(item.href)} data-tooltip={item.label}>
                <i className={`fa ${item.icon}`} aria-hidden="true" />
                <span>{item.label}</span>
              </a>
            ))}
          </nav>
        </aside>
        <main className="dashboard-main finance-surface">
          <div className="finance-loading">
            <i className="fa fa-spinner fa-spin fa-3x" />
            <p>Carregando dados financeiros...</p>
          </div>
        </main>
      </div>
    )
  }

  return (
    <div className={`dashboard-shell ${collapsed ? 'is-collapsed' : ''}`}>
      <aside className="dashboard-sidebar">
        <div className="dashboard-sidebar__brand">
          <div className="dashboard-logo-wrap">
            <img src="/static/images/5.svg" alt="Ponza Health" className="dashboard-logo dashboard-logo--full" />
            <img src="/static/images/15.svg" alt="Ponza Health" className="dashboard-logo dashboard-logo--compact" />
          </div>
          <button
            className="dashboard-toggle"
            type="button"
            onClick={() => {
              const next = !collapsed
              setCollapsed(next)
              localStorage.setItem('dashboardSidebar', next ? '1' : '0')
            }}
            aria-label="Alternar menu"
          >
            <i className="fa fa-bars" />
          </button>
        </div>
        <nav className="dashboard-nav" aria-label="Menu principal">
          {sidebarNav.map((item) => (
            <a
              key={item.href}
              className={`dashboard-link ${isActiveLink(item.href) ? 'is-active' : ''}`}
              href={withBackend(item.href)}
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

      <main className="dashboard-main finance-surface">
        {/* Header Section */}
        <section className="finance-hero">
          <div className="finance-hero__header">
            <span className="finance-pill">Gestão Financeira</span>
            <h1>Central Financeira</h1>
            <p className="finance-lead">
              Controle completo de caixas, pagamentos de pacientes e fluxo de caixa da sua clínica.
            </p>
          </div>
          
          {/* Quick Stats */}
          <div className="finance-hero__kpis">
            <div className="finance-stat finance-stat--highlight">
              <p>Saldo Total</p>
              <strong>{formatCurrency(summary?.total_balance || 0)}</strong>
              <small>{summary?.open_cashboxes || 0} caixas abertos</small>
            </div>
            <div className="finance-stat">
              <p>Receita ({timeframe})</p>
              <strong className="text-success">{formatCurrency(summary?.total_income || 0)}</strong>
              <small>Entradas no período</small>
            </div>
            <div className="finance-stat">
              <p>Despesas ({timeframe})</p>
              <strong className="text-danger">{formatCurrency(summary?.total_expense || 0)}</strong>
              <small>Saídas no período</small>
            </div>
            <div className="finance-stat">
              <p>Período</p>
              <div className="finance-timeframe">
                {['7d', '30d', '90d', '365d'].map((option) => (
                  <button
                    key={option}
                    type="button"
                    className={`finance-chip ${timeframe === option ? 'is-active' : ''}`}
                    onClick={() => setTimeframe(option)}
                  >
                    {option === '365d' ? '1a' : option}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </section>

        {/* Tab Navigation */}
        <div className="finance-tabs">
          <button
            type="button"
            className={`finance-tab ${activeTab === 'overview' ? 'is-active' : ''}`}
            onClick={() => setActiveTab('overview')}
          >
            <i className="fa fa-dashboard" /> Visão Geral
          </button>
          <button
            type="button"
            className={`finance-tab ${activeTab === 'cashboxes' ? 'is-active' : ''}`}
            onClick={() => setActiveTab('cashboxes')}
          >
            <i className="fa fa-inbox" /> Caixas
          </button>
          <button
            type="button"
            className={`finance-tab ${activeTab === 'payments' ? 'is-active' : ''}`}
            onClick={() => setActiveTab('payments')}
          >
            <i className="fa fa-money" /> Pagamentos de Pacientes
          </button>
        </div>

        {/* Overview Tab */}
        {activeTab === 'overview' && (
          <>
            {/* KPI Cards */}
            <div className="finance-grid finance-grid--kpis">
              <article className="finance-card">
                <div className="finance-card__meta">
                  <span className="finance-dot finance-dot--positive" />
                  <span className="finance-card__label">Resultado Líquido</span>
                </div>
                <div className="finance-card__value">{formatCurrency(summary?.net_result || 0)}</div>
                <p className={`finance-card__trend finance-card__trend--${(summary?.net_result || 0) >= 0 ? 'positive' : 'negative'}`}>
                  Margem: {summary?.margin_percent || 0}%
                </p>
              </article>
              <article className="finance-card">
                <div className="finance-card__meta">
                  <span className="finance-dot finance-dot--info" />
                  <span className="finance-card__label">Ticket Médio</span>
                </div>
                <div className="finance-card__value">{formatCurrency(summary?.avg_ticket || 0)}</div>
                <p className="finance-card__trend finance-card__trend--neutral">Por pagamento recebido</p>
              </article>
              <article className="finance-card">
                <div className="finance-card__meta">
                  <span className="finance-dot finance-dot--warn" />
                  <span className="finance-card__label">A Receber</span>
                </div>
                <div className="finance-card__value">{formatCurrency(summary?.total_pending || 0)}</div>
                <p className="finance-card__trend finance-card__trend--warn">Pagamentos pendentes</p>
              </article>
              <article className="finance-card">
                <div className="finance-card__meta">
                  <span className="finance-dot finance-dot--positive" />
                  <span className="finance-card__label">Recebido</span>
                </div>
                <div className="finance-card__value">{formatCurrency(summary?.total_received || 0)}</div>
                <p className="finance-card__trend finance-card__trend--positive">No período</p>
              </article>
            </div>

            <div className="finance-grid finance-grid--wide">
              {/* Monthly Chart */}
              <section className="finance-panel">
                <header className="finance-panel__head">
                  <div>
                    <p className="finance-panel__eyebrow">Evolução</p>
                    <h2>Entradas vs Saídas</h2>
                  </div>
                  <div className="finance-legend">
                    <span className="legend-dot legend-dot--income" /> Entradas
                    <span className="legend-dot legend-dot--expense" /> Saídas
                  </div>
                </header>
                {monthlyData.length > 0 ? (
                  <MultiBarChart data={monthlyData} />
                ) : (
                  <p className="finance-empty">Nenhum dado disponível para o período</p>
                )}
              </section>

              {/* Receivables Breakdown */}
              <section className="finance-panel finance-panel--stacked">
                <header className="finance-panel__head">
                  <div>
                    <p className="finance-panel__eyebrow">Recebíveis</p>
                    <h2>Por vencimento</h2>
                  </div>
                </header>
                <div className="finance-receivables-grid">
                  <div className="finance-receivable-card finance-receivable-card--urgent">
                    <i className="fa fa-exclamation-circle" />
                    <div>
                      <p className="finance-receivable__label">Vencidos / Hoje</p>
                      <strong>{formatCurrency(summary?.receivables?.today || 0)}</strong>
                    </div>
                  </div>
                  <div className="finance-receivable-card finance-receivable-card--soon">
                    <i className="fa fa-clock-o" />
                    <div>
                      <p className="finance-receivable__label">Próximos 7 dias</p>
                      <strong>{formatCurrency(summary?.receivables?.week || 0)}</strong>
                    </div>
                  </div>
                  <div className="finance-receivable-card finance-receivable-card--later">
                    <i className="fa fa-calendar-o" />
                    <div>
                      <p className="finance-receivable__label">Mais de 7 dias</p>
                      <strong>{formatCurrency(summary?.receivables?.later || 0)}</strong>
                    </div>
                  </div>
                </div>
                
                <header className="finance-panel__head" style={{ marginTop: '1.5rem' }}>
                  <div>
                    <p className="finance-panel__eyebrow">Pagamentos</p>
                    <h2>Por método</h2>
                  </div>
                </header>
                <PaymentMethodBreakdown methods={paymentMethods} />
              </section>
            </div>

            {/* Quick Actions */}
            <section className="finance-panel finance-panel--actions">
              <header className="finance-panel__head">
                <div>
                  <p className="finance-panel__eyebrow">Ações Rápidas</p>
                  <h2>O que você precisa fazer?</h2>
                </div>
              </header>
              <div className="finance-actions">
                <button type="button" className="finance-action-card" onClick={() => setShowNewCashbox(true)}>
                  <div className="finance-action-icon finance-action-icon--primary">
                    <i className="fa fa-inbox" />
                  </div>
                  <span>Abrir Novo Caixa</span>
                  <small>Crie um caixa para controlar entradas e saídas</small>
                </button>
                <button type="button" className="finance-action-card" onClick={() => setShowNewPayment(true)}>
                  <div className="finance-action-icon finance-action-icon--success">
                    <i className="fa fa-file-text-o" />
                  </div>
                  <span>Nova Cobrança</span>
                  <small>Registre uma nova cobrança para um paciente</small>
                </button>
                <button type="button" className="finance-action-card" onClick={() => setActiveTab('cashboxes')}>
                  <div className="finance-action-icon finance-action-icon--info">
                    <i className="fa fa-list-alt" />
                  </div>
                  <span>Gerenciar Caixas</span>
                  <small>Visualize e controle todos os seus caixas</small>
                </button>
                <button type="button" className="finance-action-card" onClick={() => setActiveTab('payments')}>
                  <div className="finance-action-icon finance-action-icon--warn">
                    <i className="fa fa-credit-card" />
                  </div>
                  <span>Ver Pagamentos</span>
                  <small>Acompanhe as cobranças dos pacientes</small>
                </button>
              </div>
            </section>
          </>
        )}

        {/* Cashboxes Tab */}
        {activeTab === 'cashboxes' && (
          <section className="finance-panel">
            <header className="finance-panel__head">
              <div>
                <p className="finance-panel__eyebrow">Gestão de Caixas</p>
                <h2>Controle de Caixas</h2>
              </div>
              <div className="finance-panel__actions">
                <div className="finance-filters">
                  <select
                    className="dashboard-select"
                    value={cashboxFilter}
                    onChange={(e) => setCashboxFilter(e.target.value)}
                  >
                    <option value="all">Todos</option>
                    <option value="open">Abertos</option>
                    <option value="closed">Fechados</option>
                  </select>
                </div>
                <button type="button" className="btn-primary" onClick={() => setShowNewCashbox(true)}>
                  <i className="fa fa-plus-circle" /> Novo Caixa
                </button>
              </div>
            </header>

            {cashboxes.length === 0 ? (
              <div className="finance-empty-state">
                <i className="fa fa-inbox fa-3x" />
                <h3>Nenhum caixa encontrado</h3>
                <p>Comece criando seu primeiro caixa para controlar suas movimentações.</p>
                <button type="button" className="btn-primary" onClick={() => setShowNewCashbox(true)}>
                  <i className="fa fa-plus-circle" /> Criar Primeiro Caixa
                </button>
              </div>
            ) : (
              <div className="cashbox-grid">
                {cashboxes.map((cb) => (
                  <article key={cb.id} className={`cashbox-card ${cb.status === 'open' ? 'cashbox-card--open' : 'cashbox-card--closed'}`}>
                    <header className="cashbox-card__header">
                      <h3>{cb.name}</h3>
                      {statusBadge(cb.status)}
                    </header>
                    <div className="cashbox-card__balance">
                      <span className="cashbox-card__balance-label">Saldo atual</span>
                      <strong>{formatCurrency(cb.current_balance)}</strong>
                    </div>
                    <div className="cashbox-card__meta">
                      <span><i className="fa fa-user" /> {cb.responsible || '—'}</span>
                      <span><i className="fa fa-clock-o" /> {formatDateTime(cb.opened_at)}</span>
                      {cb.today_transactions > 0 && (
                        <span><i className="fa fa-exchange" /> {cb.today_transactions} mov. hoje</span>
                      )}
                    </div>
                    <div className="cashbox-card__actions">
                      <button type="button" className="btn-outline btn-small" onClick={() => fetchCashboxDetail(cb.id)}>
                        <i className="fa fa-eye" /> Ver Detalhes
                      </button>
                      {cb.status === 'open' && (
                        <>
                          <button type="button" className="btn-success btn-small" onClick={() => setShowTransaction(cb)}>
                            <i className="fa fa-plus-circle" /> Lançamento
                          </button>
                          <button type="button" className="btn-outline btn-small" onClick={() => handleCashboxAction(cb.id, 'close')}>
                            <i className="fa fa-lock" /> Fechar
                          </button>
                        </>
                      )}
                      {cb.status === 'closed' && (
                        <button type="button" className="btn-outline btn-small" onClick={() => handleCashboxAction(cb.id, 'reopen')}>
                          <i className="fa fa-unlock" /> Reabrir
                        </button>
                      )}
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>
        )}

        {/* Payments Tab */}
        {activeTab === 'payments' && (
          <section className="finance-panel">
            <header className="finance-panel__head">
              <div>
                <p className="finance-panel__eyebrow">Pagamentos</p>
                <h2>Cobranças de Pacientes</h2>
              </div>
              <div className="finance-panel__actions">
                <div className="finance-filters">
                  <select
                    className="dashboard-select"
                    value={paymentFilter}
                    onChange={(e) => setPaymentFilter(e.target.value)}
                  >
                    <option value="all">Todos</option>
                    <option value="pending">Pendentes</option>
                    <option value="paid">Pagos</option>
                  </select>
                </div>
                <button type="button" className="btn-primary" onClick={() => setShowNewPayment(true)}>
                  <i className="fa fa-plus-circle" /> Nova Cobrança
                </button>
              </div>
            </header>

            {payments.length === 0 ? (
              <div className="finance-empty-state">
                <i className="fa fa-money fa-3x" />
                <h3>Nenhuma cobrança encontrada</h3>
                <p>Crie cobranças para acompanhar os pagamentos dos seus pacientes.</p>
                <button type="button" className="btn-primary" onClick={() => setShowNewPayment(true)}>
                  <i className="fa fa-plus-circle" /> Criar Primeira Cobrança
                </button>
              </div>
            ) : (
              <div className="finance-table finance-table--payments">
                <div className="finance-table__head">
                  <span>Paciente</span>
                  <span>Tipo</span>
                  <span>Valor</span>
                  <span>Pago</span>
                  <span>Saldo</span>
                  <span>Vencimento</span>
                  <span>Status</span>
                  <span>Ações</span>
                </div>
                {payments.map((p) => {
                  const paymentTypeLabels = {
                    'consultation': 'Consulta',
                    'exam': 'Exame',
                    'procedure': 'Procedimento',
                    'other': 'Outro'
                  }
                  return (
                  <div className="finance-table__row" key={p.id}>
                    <span className="finance-table__patient">{p.patient_name}</span>
                    <span className="finance-table__type">{paymentTypeLabels[p.payment_type] || p.payment_type}</span>
                    <span>{formatCurrency(p.amount)}</span>
                    <span className="text-success">{formatCurrency(p.amount_paid)}</span>
                    <span className={p.balance > 0 ? 'text-danger' : ''}>{formatCurrency(p.balance)}</span>
                    <span>{p.due_date ? formatDate(p.due_date) : '—'}</span>
                    <span>{statusBadge(p.status)}</span>
                    <span className="finance-table__actions">
                      {p.status !== 'paid' && p.status !== 'cancelled' && (
                        <button
                          type="button"
                          className="btn-success btn-small"
                          onClick={() => {
                            setShowReceivePayment(p)
                            setReceiveForm({ amount: p.balance, payment_method: 'cash', cashbox_id: '' })
                          }}
                        >
                          <i className="fa fa-check" /> Receber
                        </button>
                      )}
                    </span>
                  </div>
                  )
                })}
              </div>
            )}
          </section>
        )}
      </main>

      {/* Modal: New Cashbox */}
      <Modal isOpen={showNewCashbox} onClose={() => setShowNewCashbox(false)} title="Abrir Novo Caixa">
        <form onSubmit={handleCreateCashbox} className="finance-form">
          <div className="form-group">
            <label>Nome do Caixa *</label>
            <input
              type="text"
              className="dashboard-input"
              value={newCashboxForm.name}
              onChange={(e) => setNewCashboxForm({ ...newCashboxForm, name: e.target.value })}
              placeholder="Ex: Recepção, Laboratório..."
              required
            />
          </div>
          <div className="form-group">
            <label>Descrição</label>
            <input
              type="text"
              className="dashboard-input"
              value={newCashboxForm.description}
              onChange={(e) => setNewCashboxForm({ ...newCashboxForm, description: e.target.value })}
              placeholder="Descrição opcional"
            />
          </div>
          <div className="form-row">
            <div className="form-group">
              <label>Saldo Inicial</label>
              <input
                type="number"
                step="0.01"
                className="dashboard-input"
                value={newCashboxForm.initial_balance}
                onChange={(e) => setNewCashboxForm({ ...newCashboxForm, initial_balance: e.target.value })}
              />
            </div>
            <div className="form-group">
              <label>Responsável</label>
              <input
                type="text"
                className="dashboard-input"
                value={newCashboxForm.responsible}
                onChange={(e) => setNewCashboxForm({ ...newCashboxForm, responsible: e.target.value })}
                placeholder="Nome do responsável"
              />
            </div>
          </div>
          <div className="form-actions">
            <button type="button" className="btn-outline" onClick={() => setShowNewCashbox(false)}>Cancelar</button>
            <button type="submit" className="btn-primary">Abrir Caixa</button>
          </div>
        </form>
      </Modal>

      {/* Modal: Add Transaction */}
      <Modal isOpen={!!showTransaction} onClose={() => setShowTransaction(null)} title={`Lançamento - ${showTransaction?.name || ''}`} zIndex={3300}>
        <form onSubmit={handleAddTransaction} className="finance-form">
          <div className="form-group">
            <label>Tipo de Lançamento *</label>
            <div className="transaction-type-selector">
              <button
                type="button"
                className={`transaction-type-btn ${transactionForm.type === 'income' ? 'is-active is-income' : ''}`}
                onClick={() => setTransactionForm({ ...transactionForm, type: 'income' })}
              >
                <i className="fa fa-arrow-down" /> Entrada
              </button>
              <button
                type="button"
                className={`transaction-type-btn ${transactionForm.type === 'expense' ? 'is-active is-expense' : ''}`}
                onClick={() => setTransactionForm({ ...transactionForm, type: 'expense' })}
              >
                <i className="fa fa-arrow-up" /> Saída
              </button>
            </div>
          </div>
          <div className="form-row">
            <div className="form-group">
              <label>Valor *</label>
              <input
                type="number"
                step="0.01"
                min="0.01"
                className="dashboard-input"
                value={transactionForm.amount}
                onChange={(e) => setTransactionForm({ ...transactionForm, amount: e.target.value })}
                required
              />
            </div>
            <div className="form-group">
              <label>Forma de Pagamento</label>
              <select
                className="dashboard-select"
                value={transactionForm.payment_method}
                onChange={(e) => setTransactionForm({ ...transactionForm, payment_method: e.target.value })}
              >
                <option value="cash">Dinheiro</option>
                <option value="pix">PIX</option>
                <option value="credit_card">Cartão de Crédito</option>
                <option value="debit_card">Cartão de Débito</option>
                <option value="transfer">Transferência</option>
                <option value="check">Cheque</option>
              </select>
            </div>
          </div>
          <div className="form-group">
            <label>Categoria</label>
            <input
              type="text"
              className="dashboard-input"
              value={transactionForm.category}
              onChange={(e) => setTransactionForm({ ...transactionForm, category: e.target.value })}
              placeholder="Ex: Consulta, Material, Aluguel..."
            />
          </div>
          <div className="form-group">
            <label>Descrição</label>
            <input
              type="text"
              className="dashboard-input"
              value={transactionForm.description}
              onChange={(e) => setTransactionForm({ ...transactionForm, description: e.target.value })}
              placeholder="Descrição do lançamento"
            />
          </div>
          <div className="form-actions">
            <button type="button" className="btn-outline" onClick={() => setShowTransaction(null)}>Cancelar</button>
            <button type="submit" className={`btn-primary ${transactionForm.type === 'income' ? 'btn-success' : 'btn-danger'}`}>
              Registrar {transactionForm.type === 'income' ? 'Entrada' : 'Saída'}
            </button>
          </div>
        </form>
      </Modal>

      {/* Modal: New Patient Payment */}
      <Modal isOpen={showNewPayment} onClose={() => setShowNewPayment(false)} title="Nova Cobrança">
        <form onSubmit={handleCreatePayment} className="finance-form">
          <div className="form-group">
            <label>Paciente *</label>
            <select
              className="dashboard-select"
              value={newPaymentForm.patient_id}
              onChange={(e) => setNewPaymentForm({ ...newPaymentForm, patient_id: e.target.value })}
              required
            >
              <option value="">Selecione um paciente</option>
              {patients.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </div>
          <div className="form-row">
            <div className="form-group">
              <label>Valor *</label>
              <input
                type="number"
                step="0.01"
                min="0.01"
                className="dashboard-input"
                value={newPaymentForm.amount}
                onChange={(e) => setNewPaymentForm({ ...newPaymentForm, amount: e.target.value })}
                required
              />
            </div>
            <div className="form-group">
              <label>Tipo</label>
              <select
                className="dashboard-select"
                value={newPaymentForm.payment_type}
                onChange={(e) => setNewPaymentForm({ ...newPaymentForm, payment_type: e.target.value })}
              >
                <option value="consultation">Consulta</option>
                <option value="exam">Exame</option>
                <option value="procedure">Procedimento</option>
                <option value="other">Outro</option>
              </select>
            </div>
          </div>
          <div className="form-group">
            <label>Vencimento</label>
            <input
              type="date"
              className="dashboard-input"
              value={newPaymentForm.due_date}
              onChange={(e) => setNewPaymentForm({ ...newPaymentForm, due_date: e.target.value })}
            />
          </div>
          <div className="form-group">
            <label>Descrição</label>
            <input
              type="text"
              className="dashboard-input"
              value={newPaymentForm.description}
              onChange={(e) => setNewPaymentForm({ ...newPaymentForm, description: e.target.value })}
              placeholder="Descrição da cobrança"
            />
          </div>
          <div className="form-actions">
            <button type="button" className="btn-outline" onClick={() => setShowNewPayment(false)}>Cancelar</button>
            <button type="submit" className="btn-primary">Criar Cobrança</button>
          </div>
        </form>
      </Modal>

      {/* Modal: Receive Payment */}
      <Modal isOpen={!!showReceivePayment} onClose={() => setShowReceivePayment(null)} title="Receber Pagamento">
        <form onSubmit={handleReceivePayment} className="finance-form">
          <div className="receive-payment-info">
            <p><strong>Paciente:</strong> {showReceivePayment?.patient_name}</p>
            <p><strong>Valor total:</strong> {formatCurrency(showReceivePayment?.amount)}</p>
            <p><strong>Já pago:</strong> {formatCurrency(showReceivePayment?.amount_paid)}</p>
            <p><strong>Saldo restante:</strong> <span className="text-danger">{formatCurrency(showReceivePayment?.balance)}</span></p>
          </div>
          <div className="form-row">
            <div className="form-group">
              <label>Valor a Receber *</label>
              <input
                type="number"
                step="0.01"
                min="0.01"
                max={showReceivePayment?.balance || 0}
                className="dashboard-input"
                value={receiveForm.amount}
                onChange={(e) => setReceiveForm({ ...receiveForm, amount: e.target.value })}
                required
              />
            </div>
            <div className="form-group">
              <label>Forma de Pagamento</label>
              <select
                className="dashboard-select"
                value={receiveForm.payment_method}
                onChange={(e) => setReceiveForm({ ...receiveForm, payment_method: e.target.value })}
              >
                <option value="cash">Dinheiro</option>
                <option value="pix">PIX</option>
                <option value="credit_card">Cartão de Crédito</option>
                <option value="debit_card">Cartão de Débito</option>
                <option value="transfer">Transferência</option>
                <option value="check">Cheque</option>
                <option value="insurance">Convênio</option>
              </select>
            </div>
          </div>
          <div className="form-group">
            <label>Registrar no Caixa (opcional)</label>
            <select
              className="dashboard-select"
              value={receiveForm.cashbox_id}
              onChange={(e) => setReceiveForm({ ...receiveForm, cashbox_id: e.target.value })}
            >
              <option value="">Não registrar em caixa</option>
              {openCashboxes.map((cb) => (
                <option key={cb.id} value={cb.id}>{cb.name} ({formatCurrency(cb.current_balance)})</option>
              ))}
            </select>
            <small className="form-hint">Se selecionado, o valor será automaticamente adicionado ao caixa escolhido.</small>
          </div>
          <div className="form-actions">
            <button type="button" className="btn-outline" onClick={() => setShowReceivePayment(null)}>Cancelar</button>
            <button type="submit" className="btn-success">Confirmar Recebimento</button>
          </div>
        </form>
      </Modal>

      {/* Modal: Cashbox Detail */}
      <Modal isOpen={!!showCashboxDetail} onClose={() => setShowCashboxDetail(null)} title={`Caixa: ${showCashboxDetail?.name || ''}`}>
        {showCashboxDetail && (
          <div className="cashbox-detail">
            <div className="cashbox-detail__header">
              <div className="cashbox-detail__stat">
                <span>Saldo Inicial</span>
                <strong>{formatCurrency(showCashboxDetail.initial_balance)}</strong>
              </div>
              <div className="cashbox-detail__stat">
                <span>Saldo Atual</span>
                <strong className={showCashboxDetail.current_balance >= 0 ? 'text-success' : 'text-danger'}>
                  {formatCurrency(showCashboxDetail.current_balance)}
                </strong>
              </div>
              <div className="cashbox-detail__stat">
                <span>Status</span>
                {statusBadge(showCashboxDetail.status)}
              </div>
            </div>
            
            <div className="cashbox-detail__info">
              <p><i className="fa fa-user" /> <strong>Responsável:</strong> {showCashboxDetail.responsible || '—'}</p>
              <p><i className="fa fa-clock-o" /> <strong>Aberto em:</strong> {formatDateTime(showCashboxDetail.opened_at)}</p>
              {showCashboxDetail.closed_at && (
                <p><i className="fa fa-lock" /> <strong>Fechado em:</strong> {formatDateTime(showCashboxDetail.closed_at)}</p>
              )}
            </div>

            <div className="cashbox-detail__actions">
              {showCashboxDetail.status === 'open' && (
                <>
                  <button type="button" className="btn-primary" onClick={() => {
                    setShowTransaction(showCashboxDetail)
                  }}>
                    <i className="fa fa-plus-circle" /> Novo Lançamento
                  </button>
                  <button type="button" className="btn-outline" onClick={() => {
                    handleCashboxAction(showCashboxDetail.id, 'close')
                    setShowCashboxDetail(null)
                  }}>
                    <i className="fa fa-lock" /> Fechar Caixa
                  </button>
                </>
              )}
              {showCashboxDetail.status === 'closed' && (
                <button type="button" className="btn-primary" onClick={() => {
                  handleCashboxAction(showCashboxDetail.id, 'reopen')
                  setShowCashboxDetail(null)
                }}>
                  <i className="fa fa-unlock" /> Reabrir Caixa
                </button>
              )}
            </div>

            <h4>Últimas Movimentações</h4>
            {cashboxTransactions.length === 0 ? (
              <p className="finance-empty">Nenhuma movimentação registrada</p>
            ) : (
              <div className="transaction-list">
                {cashboxTransactions.map((t) => (
                  <div key={t.id} className={`transaction-item transaction-item--${t.type}`}>
                    <div className="transaction-item__icon">
                      <i className={`fa ${t.type === 'income' ? 'fa-arrow-down' : 'fa-arrow-up'}`} />
                    </div>
                    <div className="transaction-item__info">
                      <strong>{t.description || t.category || (t.type === 'income' ? 'Entrada' : 'Saída')}</strong>
                      <small>{formatDateTime(t.created_at)} • {paymentMethodLabels[t.payment_method] || t.payment_method || '—'}</small>
                    </div>
                    <div className={`transaction-item__amount ${t.type === 'income' ? 'text-success' : 'text-danger'}`}>
                      {t.type === 'income' ? '+' : ''}{formatCurrency(t.amount)}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  )
}

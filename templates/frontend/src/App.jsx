import { useEffect, useState } from 'react'
import './css/App.css'
import { RouterProvider, useRouter } from './components/Router'
import { SiteFooter } from './components/SiteFooter'
import { SiteHeader } from './components/SiteHeader'
import Ajuda from './pages/Ajuda'
import Agenda from './pages/Agenda'
import Account from './pages/Account'
import Cadastro from './pages/Cadastro'
import Dashboard from './pages/Dashboard'
import QuoteRespond from './pages/QuoteRespond'
import ForgotPassword from './pages/ForgotPassword'
import Home from './pages/Home'
import Login from './pages/Login'
import PatientForm from './pages/PatientForm'
import Planos from './pages/Planos'
import PrivacyPolicy from './pages/PrivacyPolicy'
import QuemSomos from './pages/QuemSomos'
import QuoteCreate from './pages/QuoteCreate'
import Quotes from './pages/Quotes'
import Result from './pages/Result'
import ResetPassword from './pages/ResetPassword'
import Stock from './pages/Stock'
import Terms from './pages/Terms'
import Upload from './pages/Upload'
import QuoteView from './pages/QuoteView'
import Patients from './pages/Patients'
import Payments from './pages/Payments'
import Suppliers from './pages/Suppliers'
import TrialLocked from './pages/TrialLocked'

const routes = [
  { path: '/', component: Home, shell: 'marketing' },
  { path: '/quotes/respond/:token', component: QuoteRespond, shell: 'plain' },
  { path: '/planos', component: Planos, shell: 'marketing' },
  { path: '/login', component: Login, shell: 'marketing' },
  { path: '/cadastro', component: Cadastro, shell: 'marketing' },
  { path: '/register', component: Cadastro, shell: 'marketing' },
  { path: '/forgot_password', component: ForgotPassword, shell: 'marketing' },
  { path: '/reset_password/:token', component: ResetPassword, shell: 'marketing' },
  { path: '/quem-somos', component: QuemSomos, shell: 'marketing' },
  { path: '/about', component: QuemSomos, shell: 'marketing' },
  { path: '/ajuda', component: Ajuda, shell: 'marketing' },
  { path: '/centraldeajuda', component: Ajuda, shell: 'marketing' },
  { path: '/privacy_policy', component: PrivacyPolicy, shell: 'marketing' },
  { path: '/termos', component: Terms, shell: 'marketing' },
  { path: '/trial_locked', component: TrialLocked, shell: 'plain' },
  { path: '/index', component: Dashboard, shell: 'admin' },
  { path: '/account', component: Account, shell: 'admin' },
  { path: '/payments', component: Payments, shell: 'admin' },
  { path: '/purchase', component: Payments, shell: 'admin' },
  { path: '/products', component: Stock, shell: 'admin' },
  { path: '/agenda', component: Agenda, shell: 'admin' },
  { path: '/upload', component: Upload, shell: 'admin' },
  { path: '/catalog', component: Patients, shell: 'admin' },
  { path: '/catalog/register', component: PatientForm, shell: 'admin' },
  { path: '/edit_patient/:patientId', component: PatientForm, shell: 'admin' },
  { path: '/patient_info/:patientId', component: PatientForm, shell: 'admin' },
  { path: '/quotes', component: Quotes, shell: 'admin' },
  { path: '/quotes/create', component: QuoteCreate, shell: 'admin' },
  { path: '/quotes/:quoteId/results', component: QuoteView, shell: 'admin' },
  { path: '/quotes/:quoteId', component: QuoteView, shell: 'admin' },
  { path: '/suppliers', component: Suppliers, shell: 'admin' },
  { path: '/patient_result/:patientId', component: Result, shell: 'admin' },
  { path: '/result/:patientId', component: Result, shell: 'admin' },
  { path: '/lab_analysis/view', component: Result, shell: 'admin' },
]

function AppShell() {
  const { route, path, navigate } = useRouter()
  const Page = route?.component || Home
  const shell = route?.shell || 'marketing'
  const [trialGuard, setTrialGuard] = useState({ checked: shell !== 'admin', expired: false })

  useEffect(() => {
    let active = true
    if (shell !== 'admin') {
      setTrialGuard({ checked: true, expired: false })
      return () => {
        active = false
      }
    }

    setTrialGuard((prev) => ({ ...prev, checked: false }))
    const load = async () => {
      try {
        const response = await fetch('/api/trial_status', { credentials: 'include' })
        if (response.redirected && response.url.includes('/login')) {
          window.location.href = response.url
          return
        }
        if (!response.ok) {
          throw new Error('Falha ao verificar o plano.')
        }
        const payload = await response.json()
        if (!active) return
        setTrialGuard({ checked: true, expired: Boolean(payload?.trial_expired) })
      } catch (err) {
        if (!active) return
        setTrialGuard({ checked: true, expired: false })
      }
    }
    load()

    return () => {
      active = false
    }
  }, [shell])

  useEffect(() => {
    if (shell !== 'admin') return
    if (!trialGuard.checked) return
    if (trialGuard.expired && path !== '/trial_locked') {
      navigate('/trial_locked')
    }
  }, [shell, trialGuard.checked, trialGuard.expired, path, navigate])

  if (shell === 'admin') {
    if (!trialGuard.checked) {
      return <div className="app-loading">Carregando...</div>
    }
    if (trialGuard.expired) {
      return <TrialLocked />
    }
  }

  if (shell === 'admin' || shell === 'plain') {
    return <Page />
  }

  return (
    <div className="page-shell">
      <SiteHeader />
      <main className="page-content">
        <Page />
      </main>
      <SiteFooter />
    </div>
  )
}

export default function App() {
  return (
    <RouterProvider routes={routes}>
      <AppShell />
    </RouterProvider>
  )
}

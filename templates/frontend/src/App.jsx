import { useEffect, useState } from 'react'
import './css/App.css'
import { RouterProvider, useRouter } from './components/Router'
import { SiteFooter } from './components/SiteFooter'
import { SiteHeader } from './components/SiteHeader'
import Ajuda from './pages/Ajuda'
import Agenda from './pages/Agenda'
import Account from './pages/Account'
import Admin from './pages/Admin'
import Cadastro from './pages/Cadastro'
import Dashboard from './pages/Dashboard'
import LabAnalysisLoading from './pages/LabAnalysisLoading'
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
  { path: '/lab_analysis/loading', component: LabAnalysisLoading, shell: 'plain' },
  { path: '/index', component: Dashboard, shell: 'app' },
  { path: '/admin', component: Admin, shell: 'app' },
  { path: '/account', component: Account, shell: 'app' },
  { path: '/payments', component: Payments, shell: 'app' },
  { path: '/purchase', component: Payments, shell: 'app' },
  { path: '/products', component: Stock, shell: 'app' },
  { path: '/agenda', component: Agenda, shell: 'app' },
  { path: '/upload', component: Upload, shell: 'app' },
  { path: '/catalog', component: Patients, shell: 'app' },
  { path: '/catalog/register', component: PatientForm, shell: 'app' },
  { path: '/edit_patient/:patientId', component: PatientForm, shell: 'app' },
  { path: '/patient_info/:patientId', component: PatientForm, shell: 'app' },
  { path: '/quotes', component: Quotes, shell: 'app' },
  { path: '/quotes/create', component: QuoteCreate, shell: 'app' },
  { path: '/quotes/:quoteId/results', component: QuoteView, shell: 'app' },
  { path: '/quotes/:quoteId', component: QuoteView, shell: 'app' },
  { path: '/suppliers', component: Suppliers, shell: 'app' },
  { path: '/patient_result/:patientId', component: Result, shell: 'app' },
  { path: '/result/:patientId', component: Result, shell: 'app' },
  { path: '/lab_analysis/view', component: Result, shell: 'app' },
]

function AppShell() {
  const { route, path, navigate } = useRouter()
  const Page = route?.component || Home
  const shell = route?.shell || 'marketing'
  const [trialGuard, setTrialGuard] = useState({ checked: shell !== 'app', expired: false })

  useEffect(() => {
    let active = true
    if (shell !== 'app') {
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
    if (shell !== 'app') return
    if (!trialGuard.checked) return
    if (trialGuard.expired && path !== '/trial_locked') {
      navigate('/trial_locked')
    }
  }, [shell, trialGuard.checked, trialGuard.expired, path, navigate])

  if (shell === 'app' && trialGuard.checked && trialGuard.expired) {
    return <TrialLocked />
  }

  if (shell === 'app' || shell === 'plain') {
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

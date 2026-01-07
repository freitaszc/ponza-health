import { Suspense, lazy, useEffect, useState } from 'react'
import './css/App.css'
import { RouterProvider, useRouter } from './components/Router'
import { SiteFooter } from './components/SiteFooter'
import { SiteHeader } from './components/SiteHeader'
import { buildCacheKey, readCache, writeCache } from './utils/cache'

const lazyWithPreload = (factory) => {
  const Component = lazy(factory)
  Component.preload = factory
  return Component
}

const Ajuda = lazyWithPreload(() => import('./pages/Ajuda'))
const Agenda = lazyWithPreload(() => import('./pages/Agenda'))
const Account = lazyWithPreload(() => import('./pages/Account'))
const Admin = lazyWithPreload(() => import('./pages/Admin'))
const Cadastro = lazyWithPreload(() => import('./pages/Cadastro'))
const Dashboard = lazyWithPreload(() => import('./pages/Dashboard'))
const LabAnalysisLoading = lazyWithPreload(() => import('./pages/LabAnalysisLoading'))
const QuoteRespond = lazyWithPreload(() => import('./pages/QuoteRespond'))
const ForgotPassword = lazyWithPreload(() => import('./pages/ForgotPassword'))
const Home = lazyWithPreload(() => import('./pages/Home'))
const Login = lazyWithPreload(() => import('./pages/Login'))
const PatientForm = lazyWithPreload(() => import('./pages/PatientForm'))
const Planos = lazyWithPreload(() => import('./pages/Planos'))
const PrivacyPolicy = lazyWithPreload(() => import('./pages/PrivacyPolicy'))
const QuemSomos = lazyWithPreload(() => import('./pages/QuemSomos'))
const QuoteCreate = lazyWithPreload(() => import('./pages/QuoteCreate'))
const Quotes = lazyWithPreload(() => import('./pages/Quotes'))
const Result = lazyWithPreload(() => import('./pages/Result'))
const ResetPassword = lazyWithPreload(() => import('./pages/ResetPassword'))
const Stock = lazyWithPreload(() => import('./pages/Stock'))
const Terms = lazyWithPreload(() => import('./pages/Terms'))
const Upload = lazyWithPreload(() => import('./pages/Upload'))
const QuoteView = lazyWithPreload(() => import('./pages/QuoteView'))
const Patients = lazyWithPreload(() => import('./pages/Patients'))
const Payments = lazyWithPreload(() => import('./pages/Payments'))
const Suppliers = lazyWithPreload(() => import('./pages/Suppliers'))
const TrialLocked = lazyWithPreload(() => import('./pages/TrialLocked'))

const scheduleIdle = (callback) => {
  if (typeof window === 'undefined') return undefined
  if ('requestIdleCallback' in window) {
    const id = window.requestIdleCallback(callback, { timeout: 1500 })
    return () => window.cancelIdleCallback(id)
  }
  const id = window.setTimeout(callback, 300)
  return () => window.clearTimeout(id)
}

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

  useEffect(() => {
    if (shell !== 'app') return undefined
    return scheduleIdle(() => {
      Dashboard.preload?.()
      Patients.preload?.()
      Agenda.preload?.()

      const dashboardKey = buildCacheKey('dashboard', ['summary'])
      if (!readCache(dashboardKey)) {
        fetch('/api/dashboard', { credentials: 'same-origin' })
          .then((response) => {
            if (!response.ok) throw new Error('Erro')
            return response.json()
          })
          .then((payload) => writeCache(dashboardKey, payload))
          .catch(() => {})
      }

      const patientsKey = buildCacheKey('patients', ['all', 'all'])
      if (!readCache(patientsKey)) {
        fetch('/api/patients', { credentials: 'include' })
          .then((response) => {
            if (!response.ok) throw new Error('Erro')
            return response.json()
          })
          .then((payload) => {
            if (payload && Array.isArray(payload.patients)) {
              writeCache(patientsKey, payload.patients)
            }
          })
          .catch(() => {})
      }

      const agendaKey = buildCacheKey('agenda', ['snapshot'])
      if (!readCache(agendaKey)) {
        fetch('/api/agenda_snapshot', { credentials: 'same-origin' })
          .then((response) => {
            if (!response.ok) throw new Error('Erro')
            return response.json()
          })
          .then((payload) => {
            if (!payload || typeof payload !== 'object') return
            writeCache(agendaKey, {
              summary: payload.summary || {},
              upcomingEvents: payload.upcoming_events || [],
              typeSummary: payload.type_summary || [],
              waitlistCount: payload.waitlist_count ?? 0,
            })
          })
          .catch(() => {})
      }
    })
  }, [shell])

  const guardedPage =
    shell === 'app' && trialGuard.checked && trialGuard.expired ? <TrialLocked /> : <Page />

  if (shell === 'app' || shell === 'plain') {
    return <Suspense fallback={null}>{guardedPage}</Suspense>
  }

  return (
    <div className="page-shell">
      <SiteHeader />
      <main className="page-content">
        <Suspense fallback={null}>{guardedPage}</Suspense>
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

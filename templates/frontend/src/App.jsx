import './css/App.css'
import { RouterProvider, useRouter } from './components/Router'
import { SiteFooter } from './components/SiteFooter'
import { SiteHeader } from './components/SiteHeader'
import Ajuda from './pages/Ajuda'
import Cadastro from './pages/Cadastro'
import QuoteRespond from './pages/QuoteRespond'
import ForgotPassword from './pages/ForgotPassword'
import Home from './pages/Home'
import Login from './pages/Login'
import Planos from './pages/Planos'
import PrivacyPolicy from './pages/PrivacyPolicy'
import QuemSomos from './pages/QuemSomos'
import ResetPassword from './pages/ResetPassword'
import Terms from './pages/Terms'

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
]

function AppShell() {
  const { route } = useRouter()
  const Page = route?.component || Home
  const shell = route?.shell || 'marketing'

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

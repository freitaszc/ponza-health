import { Link, useRouter } from './Router'

const navItems = [
  { label: 'Início', to: '/' },
  { label: 'Planos', to: '/planos' },
  { label: 'Quem somos', to: '/quem-somos' },
  { label: 'Central de ajuda', to: '/ajuda' },
]

export function SiteHeader() {
  const { path } = useRouter()

  return (
    <header className="navbar">
      <div className="container nav-inner">
        <Link className="brand" to="/" aria-label="Ponza Health">
          <img src="/static/images/5.svg" alt="Ponza Health" />
        </Link>

        <nav className="nav-links" aria-label="Navegação principal">
          {navItems.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              className={`nav-link ${path === item.to ? 'is-active' : ''}`}
              aria-current={path === item.to ? 'page' : undefined}
            >
              {item.label}
            </Link>
          ))}
        </nav>

        <div className="nav-actions">
          <Link className="btn-ghost" to="/login">
            Entrar
          </Link>
          <Link className="btn-primary" to="/cadastro">
            Cadastrar
          </Link>
        </div>
      </div>
    </header>
  )
}

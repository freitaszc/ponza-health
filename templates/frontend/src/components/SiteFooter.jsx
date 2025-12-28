import { Link } from './Router'

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="container footer-grid">
        <div className="footer-brand">
          <img src="/static/images/ponzalogo.svg" alt="Ponza Health" />
          <p>
            Plataforma completa para gestão clínica com agenda, estoque, cotações e análises automatizadas. Menos
            tarefas repetitivas, mais tempo para o cuidado.
          </p>
          <div className="footer-actions">
            <Link className="btn-outline" to="/planos">
              Ver planos
            </Link>
            <Link className="btn-primary" to="/cadastro">
              Criar conta
            </Link>
          </div>
        </div>

        <div>
          <h4>Funcionalidades</h4>
          <ul className="link-list">
            <li>
              <Link to="/#recursos">Prontuário eletrônico</Link>
            </li>
            <li>
              <Link to="/#recursos">Controle de estoque</Link>
            </li>
            <li>
              <Link to="/#recursos">Agenda múltipla</Link>
            </li>
            <li>
              <Link to="/#integracoes">Integrações</Link>
            </li>
          </ul>
        </div>

        <div>
          <h4>Institucional</h4>
          <ul className="link-list">
            <li>
              <Link to="/quem-somos">Quem somos</Link>
            </li>
            <li>
              <Link to="/ajuda">Central de ajuda</Link>
            </li>
            <li>
              <Link to="/planos">Planos</Link>
            </li>
          </ul>
        </div>

        <div>
          <h4>Contato</h4>
          <ul className="link-list">
            <li>
              <a href="mailto:contato@ponzahealth.com">contato@ponzahealth.com</a>
            </li>
            <li>
              <a href="tel:+5533984613689">+55 33 98461-3689</a>
            </li>
            <li>
              <a href="https://wa.me/5533984613689" target="_blank" rel="noreferrer">
                WhatsApp comercial
              </a>
            </li>
          </ul>
        </div>
      </div>

      <div className="container footer-bottom">
        <span>© {new Date().getFullYear()} Ponza Health. Todos os direitos reservados.</span>
        <div className="footer-links">
          <Link to="/privacy_policy">Política de privacidade</Link>
          <Link to="/termos">Termos de uso</Link>
        </div>
      </div>
    </footer>
  )
}

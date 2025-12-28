import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

const RouterContext = createContext(null)

const normalizePath = (path) => {
  if (!path || path === '/') return '/'
  return path.replace(/\/+$/, '')
}

const stripQuery = (path) => (path || '').split('?')[0]

const matchPath = (pattern, path) => {
  const cleanPattern = normalizePath(stripQuery(pattern))
  const cleanPath = normalizePath(stripQuery(path))
  const patternParts = cleanPattern.split('/').filter(Boolean)
  const pathParts = cleanPath.split('/').filter(Boolean)

  if (patternParts.length !== pathParts.length) {
    return null
  }

  const params = {}
  for (let i = 0; i < patternParts.length; i += 1) {
    const part = patternParts[i]
    const value = pathParts[i]
    if (part.startsWith(':')) {
      params[part.slice(1)] = decodeURIComponent(value)
      continue
    }
    if (part !== value) {
      return null
    }
  }

  return params
}

const getMatchedRoute = (routes, path) => {
  if (!Array.isArray(routes)) {
    return { path: normalizePath(stripQuery(path)), route: null, params: {} }
  }
  for (const route of routes) {
    const params = matchPath(route.path, path)
    if (params) {
      return { path: normalizePath(stripQuery(path)), route, params }
    }
  }
  const fallback = routes.find((route) => route.path === '/') || null
  return { path: normalizePath(stripQuery(path)), route: fallback, params: {} }
}

const getRouteFromLocation = (routes) => {
  const currentPath = normalizePath(stripQuery(window.location.pathname))
  const matched = getMatchedRoute(routes, currentPath)
  if (matched.route) {
    return matched
  }

  const hashPath = window.location.hash.startsWith('#/')
    ? normalizePath(stripQuery(window.location.hash.slice(1)))
    : null

  if (hashPath) {
    return getMatchedRoute(routes, hashPath)
  }

  return getMatchedRoute(routes, '/')
}

const scrollToHash = (hash) => {
  const target = document.getElementById(decodeURIComponent(hash))
  if (target) {
    target.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

export function RouterProvider({ children, routes }) {
  const [state, setState] = useState(() => getRouteFromLocation(routes))

  const navigate = useCallback(
    (to) => {
      const [pathPart, hashPart] = to.split('#')
      const nextPath = normalizePath(pathPart || '/')
      const nextHash = hashPart ? `#${hashPart}` : ''
      const nextUrl = `${nextPath}${nextHash}`

      if (nextUrl !== `${window.location.pathname}${window.location.hash}`) {
        window.history.pushState({}, '', nextUrl)
      }

      setState(getRouteFromLocation(routes))

      if (hashPart) {
        requestAnimationFrame(() => requestAnimationFrame(() => scrollToHash(hashPart)))
      } else {
        window.scrollTo({ top: 0, behavior: 'smooth' })
      }
    },
    [routes],
  )

  const value = useMemo(() => ({ ...state, navigate }), [state, navigate])

  useEffect(() => {
    const handleRouteChange = () => {
      setState(getRouteFromLocation(routes))
      const hash = window.location.hash.replace('#', '')
      if (hash) {
        requestAnimationFrame(() => scrollToHash(hash))
      }
    }

    window.addEventListener('popstate', handleRouteChange)
    window.addEventListener('hashchange', handleRouteChange)

    return () => {
      window.removeEventListener('popstate', handleRouteChange)
      window.removeEventListener('hashchange', handleRouteChange)
    }
  }, [routes])

  return <RouterContext.Provider value={value}>{children}</RouterContext.Provider>
}

export function useRouter() {
  const context = useContext(RouterContext)
  if (!context) {
    throw new Error('useRouter must be used within RouterProvider')
  }
  return context
}

export function Link({ to, className, children, onClick, ...rest }) {
  const { navigate } = useRouter()

  const handleClick = (event) => {
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.altKey ||
      event.ctrlKey ||
      event.shiftKey
    ) {
      return
    }

    const isExternal = /^(https?:|mailto:|tel:)/.test(to)
    const isAnchor = to.startsWith('#')

    if (isExternal || isAnchor) {
      return
    }

    event.preventDefault()
    navigate(to)
  }

  return (
    <a href={to} className={className} onClick={onClick ?? handleClick} {...rest}>
      {children}
    </a>
  )
}

const DEFAULT_TTL_MS = 5 * 60 * 1000

const normalizePart = (value) => {
  if (value === undefined || value === null || value === '') {
    return 'all'
  }
  return String(value)
}

export const buildCacheKey = (prefix, parts = []) => {
  const safeParts = parts.map(normalizePart)
  return ['ponza', prefix, ...safeParts].join(':')
}

export const readCache = (key, ttlMs = DEFAULT_TTL_MS) => {
  if (typeof window === 'undefined') return null
  try {
    const raw = sessionStorage.getItem(key)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return null
    const { ts, data } = parsed
    if (!ts) return null
    if (ttlMs && Date.now() - ts > ttlMs) {
      sessionStorage.removeItem(key)
      return null
    }
    return data
  } catch (error) {
    return null
  }
}

export const writeCache = (key, data) => {
  if (typeof window === 'undefined') return
  try {
    sessionStorage.setItem(key, JSON.stringify({ ts: Date.now(), data }))
  } catch (error) {
    // ignore storage failures
  }
}

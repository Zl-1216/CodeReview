// HTTP client for the code review backend.
// All paths are relative — Vite's dev-server proxy forwards /api to the
// backend. Set VITE_API_BASE in production builds to a fully-qualified
// origin (e.g. https://reviews.example.com/api) to skip the proxy.
const BASE = import.meta?.env?.VITE_API_BASE || '/api'

// Per-call timeout. The submit endpoint is allowed longer because it
// also returns immediately (the review runs in the background); this
// caps the *network* wait, not the review itself.
const DEFAULT_TIMEOUT_MS = 30_000
const SUBMIT_TIMEOUT_MS = 30_000
const UPLOAD_TIMEOUT_MS = 60_000

// --- API key handling -----------------------------------------------------
// When the server is configured with REVIEW_API_KEY, every write
// endpoint (review, upload, cancel, rerun, /api/git/remote/*) requires
// a matching `Authorization: Bearer <key>` header. We persist the
// user's key in localStorage so they enter it once per browser.
// 401 responses clear the stored key (the server has just told us the
// key is no longer valid) so the UI can prompt the user to re-enter.
const API_KEY_STORAGE = 'codereview.apiKey'

export function getApiKey() {
  try {
    return localStorage.getItem(API_KEY_STORAGE) || ''
  } catch {
    return ''
  }
}

export function setApiKey(key) {
  try {
    if (key) localStorage.setItem(API_KEY_STORAGE, key)
    else localStorage.removeItem(API_KEY_STORAGE)
  } catch {
    // private mode / disabled storage — best effort
  }
}

export function clearApiKey() {
  setApiKey('')
}

function timeoutSignal(ms, external) {
  // Combine an external AbortSignal (so callers can cancel) with our
  // own timeout. Either side aborting kills the fetch.
  // The previous version took an `AbortSignal.timeout()` fast path
  // when no external signal was supplied, which silently dropped any
  // signal attached by the caller (e.g. a component-level AbortController
  // for unmount cleanup). Always go through the controller so a
  // future caller-supplied signal works too.
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(new DOMException('Timeout', 'TimeoutError')), ms)
  if (external) {
    if (external.aborted) ctrl.abort(external.reason)
    else external.addEventListener('abort', () => ctrl.abort(external.reason), { once: true })
  }
  ctrl.signal.addEventListener('abort', () => clearTimeout(t), { once: true })
  return ctrl.signal
}

async function request(path, { timeoutMs = DEFAULT_TIMEOUT_MS, ...options } = {}) {
  const signal = timeoutSignal(timeoutMs, options.signal)
  // Build headers. We don't blindly spread the caller's headers because
  // we want to make sure Content-Type and Authorization are always set
  // (or not) on our terms. The caller can still override via
  // `options.headers`, which we apply last.
  const headers = { 'Content-Type': 'application/json' }
  const apiKey = getApiKey()
  if (apiKey) headers['Authorization'] = `Bearer ${apiKey}`
  if (options.headers) Object.assign(headers, options.headers)
  const resp = await fetch(BASE + path, {
    ...options,
    headers,
    signal,
  })
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`
    try {
      const body = await resp.json()
      detail = body.detail || detail
    } catch {
      // ignore — fall back to status text
    }
    // 401 = the stored key is stale. Clear it so the UI prompts the
    // user to re-enter on next render. We don't clear on 403 because
    // that could also be a permission policy (rate limit) rather than
    // an auth issue.
    if (resp.status === 401 && apiKey) clearApiKey()
    throw new Error(detail)
  }
  if (resp.status === 204) return null
  return resp.json()
}

export const api = {
  health() {
    return request('/health')
  },
  config() {
    return request('/config')
  },
  listReviews(limit = 50, offset = 0) {
    return request(`/reviews?limit=${limit}&offset=${offset}`)
  },
  getReview(id) {
    return request(`/reviews/${id}`)
  },
  deleteReview(id) {
    return request(`/reviews/${id}`, { method: 'DELETE' })
  },
  cancelReview(id) {
    return request(`/reviews/${id}/cancel`, { method: 'POST' })
  },
  rerunReview(id) {
    return request(`/reviews/${id}/rerun`, { method: 'POST' })
  },
  submitReview(payload) {
    return request('/review', {
      method: 'POST',
      body: JSON.stringify(payload),
      timeoutMs: SUBMIT_TIMEOUT_MS,
    })
  },
  parseDiff(diff) {
    return request('/diff/parse', { method: 'POST', body: JSON.stringify({ diff }) })
  },
  uploadFile(file) {
    const form = new FormData()
    form.append('file', file)
    const signal = timeoutSignal(UPLOAD_TIMEOUT_MS)
    return fetch(BASE + '/upload', { method: 'POST', body: form, signal }).then(async (r) => {
      if (!r.ok) {
        let detail = `${r.status} ${r.statusText}`
        try {
          detail = (await r.json()).detail || detail
        } catch {}
        throw new Error(detail)
      }
      return r.json()
    })
  },
  // --- Git integration ------------------------------------------------
  gitStatus() {
    return request('/git/status')
  },
  gitBranches() {
    return request('/git/branches')
  },
  gitTags() {
    return request('/git/tags')
  },
  gitDiff({ base, head, path }) {
    return request('/git/diff', {
      method: 'POST',
      body: JSON.stringify({ base, head, path: path || null }),
    })
  },
  // --- Remote git integration ----------------------------------------
  // Clone (or refresh) a user-supplied remote repo on the server. The
  // returned `id` is a sha1-derived 12-char token; the same URL on
  // subsequent calls will hit the cache and skip the network round-trip
  // when within REMOTE_GIT_CACHE_TTL.
  gitRemoteClone({ url, token, refresh = false }) {
    return request('/git/remote/clone', {
      method: 'POST',
      body: JSON.stringify({ url, token: token || null, refresh }),
      timeoutMs: SUBMIT_TIMEOUT_MS * 10, // clone may take a while
    })
  },
  gitRemoteList() {
    return request('/git/remote')
  },
  gitRemoteStatus(id) {
    return request(`/git/remote/${id}`)
  },
  gitRemoteDiff(id, { base, head, path }) {
    return request(`/git/remote/${id}/diff`, {
      method: 'POST',
      body: JSON.stringify({ base, head, path: path || null }),
    })
  },
  gitRemoteDelete(id) {
    return request(`/git/remote/${id}`, { method: 'DELETE' })
  },
}

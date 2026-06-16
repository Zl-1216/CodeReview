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

// --- API key handling -----------------------------------------------------
// When the server is configured with REVIEW_API_KEY, every write
// endpoint (review, upload, cancel, rerun, /api/git/remote/*) requires
// a matching `Authorization: Bearer <key>` header. We persist the
// user's key in localStorage so they enter it once per browser.
// 401 responses clear the stored key (the server has just told us the
// key is no longer valid) so the UI can prompt the user to re-enter.
//
// We dispatch a `codereview:apikey-changed` CustomEvent on every
// mutation (set, clear, or 401 auto-clear). The InputPanel component
// listens for it so its `hasApiKey` flag stays in sync with the actual
// storage state — without this bridge, an auto-clear leaves the UI
// showing a green "API key saved ✓" indicator while localStorage is
// empty, and the next request fires with no Authorization header and
// 401s again, which is a baffling user experience.
const API_KEY_STORAGE = 'codereview.apiKey'
const API_KEY_EVENT = 'codereview:apikey-changed'

function _notifyKeyChanged() {
  if (typeof window === 'undefined') return
  try {
    window.dispatchEvent(new CustomEvent(API_KEY_EVENT))
  } catch {
    // SSR or sandboxed window — nothing to do
  }
}

export function getApiKey() {
  try {
    return localStorage.getItem(API_KEY_STORAGE) || ''
  } catch {
    return ''
  }
}

export function setApiKey(key) {
  const trimmed = (key || '').trim()
  let storageOk = true
  try {
    if (trimmed) {
      localStorage.setItem(API_KEY_STORAGE, trimmed)
    } else {
      localStorage.removeItem(API_KEY_STORAGE)
    }
  } catch (e) {
    // Safari private mode, strict cookie/storage policies, or quota
    // exhaustion all land here. We can't persist, so the key is only
    // valid for this session (and even that is best-effort since
    // getApiKey reads from storage). Surface the failure so the user
    // sees a hint in DevTools.
    storageOk = false
    if (typeof console !== 'undefined') {
      console.warn(
        '[api] REVIEW_API_KEY could not be persisted to localStorage:',
        e?.message || e,
      )
    }
  }
  _notifyKeyChanged()
  return { value: trimmed, storageOk }
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
    // Attach the HTTP status so callers can branch on the failure
    // mode (e.g. 504 timeout vs 502 network) without re-parsing the
    // human-readable message string. Kept as a plain property on the
    // Error — any await / catch code that only reads `.message` keeps
    // working unchanged.
    const err = new Error(detail)
    err.status = resp.status
    throw err
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
  // --- Remote git integration ----------------------------------------
  // The only input mode the UI supports: the user pastes a URL (+ optional
  // token), the server clones / fetches a shallow copy under
  // REMOTE_GIT_CACHE_DIR, and the user picks branches from the picker.
  // The returned `id` is a sha1-derived 12-char token; the same URL on
  // subsequent calls hits the cache and (since the staleness fix) does
  // a cheap refs-only fetch so newly-pushed branches show up right away.
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

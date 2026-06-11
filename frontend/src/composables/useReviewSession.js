import { ref, onUnmounted } from 'vue'
import { api } from '../utils/api.js'

// Live review session: subscribes to SSE events for a given review id and
// streams findings into a reactive `findings` ref. The caller is responsible
// for setting `connect(id)` once the review has been submitted.

export function useReviewSession() {
  const id = ref(null)
  const findings = ref([])
  const summary = ref(null)
  const status = ref('idle') // idle | connecting | streaming | completed | failed
  const error = ref(null)
  const durationMs = ref(null)
  const startedAt = ref(null)

  let es = null
  // Track finding identity across reconnects. Findings don't carry a
  // stable id from the AI, so we synthesize one from the fields the model
  // is least likely to rephrase differently on a replay. The set is reset
  // every time we kick off a fresh review (in `reset` / `submit`).
  let seenFindings = new Set()

  function reset() {
    // Always close the EventSource first. Without this, a caller
    // that does `reset()` without immediately calling `connect()` (the
    // common path) leaks the SSE connection until the next connect()
    // — which may never come. Connect() itself calls disconnect() at
    // the top, so this is a safe addition.
    disconnect()
    id.value = null
    findings.value = []
    summary.value = null
    error.value = null
    durationMs.value = null
    startedAt.value = null
    status.value = 'idle'
    seenFindings = new Set()
  }

  function connect(reviewId) {
    disconnect()
    id.value = reviewId
    startedAt.value = Date.now()

    try {
      es = new EventSource(`/api/reviews/${reviewId}/events`)
    } catch (e) {
      // EventSource throws synchronously when the URL is invalid or a CSP
      // / cross-origin policy blocks the connection. Surface the failure
      // to the caller so the UI doesn't sit on 'connecting' forever.
      status.value = 'failed'
      error.value = `Could not start review stream: ${e?.message || e}`
      return
    }
    status.value = 'connecting'

    es.addEventListener('status', (ev) => {
      const data = safeParse(ev.data) || {}
      if (data.status === 'streaming') status.value = 'streaming'
      else if (data.status === 'completed') status.value = 'completed'
      else if (data.status === 'failed') {
        status.value = 'failed'
        error.value = data.error
      }
    })

    es.addEventListener('findings', (ev) => {
      const data = safeParse(ev.data) || []
      if (!Array.isArray(data) || !data.length) return
      const fresh = []
      for (const f of data) {
        const key = findingKey(f)
        if (key && seenFindings.has(key)) continue
        if (key) seenFindings.add(key)
        fresh.push(f)
      }
      if (fresh.length) findings.value = findings.value.concat(fresh)
    })

    es.addEventListener('summary', (ev) => {
      const data = safeParse(ev.data)
      if (data) summary.value = data
    })

    es.addEventListener('done', (ev) => {
      const data = safeParse(ev.data) || {}
      status.value = data.status === 'failed' ? 'failed' : 'completed'
      if (data.error) error.value = data.error
      if (data.duration_ms != null) durationMs.value = data.duration_ms
      es?.close()
      es = null
    })

    es.onerror = () => {
      // EventSource auto-reconnects. If the server is gone the page will see
      //  a hard error after a few retries — surface that to the user.
      if (es && es.readyState === EventSource.CLOSED) {
        if (status.value !== 'completed' && status.value !== 'failed') {
          error.value = 'Lost connection to the review stream'
          status.value = 'failed'
        }
      }
    }
  }

  function disconnect() {
    if (es) {
      es.close()
      es = null
    }
    // If we abandoned the stream mid-flight, the UI should not stay stuck
    // on 'connecting' / 'streaming'. Leave terminal states alone so a
    // completed review remains viewable.
    if (status.value === 'connecting' || status.value === 'streaming') {
      status.value = 'idle'
    }
  }

  // Re-populate the session from a persisted Review (e.g. when the user
  // opens a row from the history list). Equivalent to `reset()` followed
  // by setting each field, but with the SSE-related state explicitly
  // marked as idle — we don't replay the live stream for past reviews.
  function hydrate(review) {
    reset()
    if (!review) return
    id.value = review.id
    findings.value = review.findings || []
    summary.value = review.summary || null
    status.value = review.status || 'completed'
    error.value = review.error || null
    durationMs.value = review.duration_ms ?? null
  }

  onUnmounted(disconnect)

  async function submit(payload) {
    reset()
    status.value = 'connecting'
    const resp = await api.submitReview(payload)
    connect(resp.id)
    return resp.id
  }

  return {
    id,
    findings,
    summary,
    status,
    error,
    durationMs,
    startedAt,
    submit,
    connect,
    disconnect,
    reset,
    hydrate,
  }
}

function safeParse(s) {
  try {
    return JSON.parse(s)
  } catch {
    return null
  }
}

// Build a stable identity for a finding so we can de-duplicate across
// SSE reconnects. The model doesn't assign ids, but (file, line, title,
// category, severity) is stable enough to catch replays. Fields like
// `detail` and `suggestion` are intentionally excluded — the model can
// rephrase them slightly across calls and we don't want to drop a real
// new finding whose prose is similar to a previous one.
//
// Returns null when no canonical field is present (e.g. legacy test
// payloads with no identifying info) — in that case the caller treats
// the finding as fresh, since there's nothing to compare against.
function findingKey(f) {
  if (!f) return null
  const parts = [
    f.file_path ?? '',
    f.line_start ?? '',
    f.line_end ?? '',
    f.title ?? '',
    f.severity ?? '',
    f.category ?? '',
  ]
  const key = parts.join('|')
  return key === '|||||' ? null : key
}

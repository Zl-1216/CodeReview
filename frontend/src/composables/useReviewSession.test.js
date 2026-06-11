import { describe, it, expect, vi, beforeEach } from 'vitest'

// We don't use the real EventSource (no server). The composable instantiates
// `new EventSource(url)` and reads events off of it, so we mock the
// constructor globally and let tests trigger handlers directly.
const instances = []
class MockEventSource {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSED = 2
  constructor(url) {
    this.url = url
    this.readyState = MockEventSource.OPEN
    this.listeners = {}
    instances.push(this)
  }
  addEventListener(name, fn) {
    (this.listeners[name] ||= []).push(fn)
  }
  emit(name, data) {
    for (const fn of this.listeners[name] || []) fn({ data })
  }
  close() {
    this.readyState = MockEventSource.CLOSED
  }
}
vi.stubGlobal('EventSource', MockEventSource)

vi.mock('../utils/api.js', () => ({
  api: {
    submitReview: vi.fn(),
  },
}))

import { useReviewSession } from './useReviewSession.js'

const last = () => instances[instances.length - 1]

describe('useReviewSession', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    instances.length = 0
  })

  it('submit() resets state, posts to /review, and connects', async () => {
    const { api } = await import('../utils/api.js')
    api.submitReview.mockResolvedValue({ id: 'r1' })
    const s = useReviewSession()

    await s.submit({ title: 't', files: [] })

    expect(s.id.value).toBe('r1')
    expect(s.status.value).toBe('connecting')
    expect(api.submitReview).toHaveBeenCalledOnce()
  })

  it('appends findings from "findings" events', async () => {
    const { api } = await import('../utils/api.js')
    api.submitReview.mockResolvedValue({ id: 'r2' })
    const s = useReviewSession()
    await s.submit({})

    last().emit('findings', JSON.stringify([{ id: 1 }, { id: 2 }]))
    last().emit('findings', JSON.stringify([{ id: 3 }]))
    expect(s.findings.value).toHaveLength(3)
    expect(s.findings.value.map((f) => f.id)).toEqual([1, 2, 3])
  })

  it('stores summary on "summary" event', async () => {
    const { api } = await import('../utils/api.js')
    api.submitReview.mockResolvedValue({ id: 'r3' })
    const s = useReviewSession()
    await s.submit({})

    last().emit('summary', JSON.stringify({ total: 5 }))
    expect(s.summary.value).toEqual({ total: 5 })
  })

  it('flips status to completed on "done" with status=completed', async () => {
    const { api } = await import('../utils/api.js')
    api.submitReview.mockResolvedValue({ id: 'r4' })
    const s = useReviewSession()
    await s.submit({})

    last().emit('done', JSON.stringify({ status: 'completed', duration_ms: 42 }))
    expect(s.status.value).toBe('completed')
    expect(s.durationMs.value).toBe(42)
  })

  it('flips status to failed and surfaces error on "done" with error', async () => {
    const { api } = await import('../utils/api.js')
    api.submitReview.mockResolvedValue({ id: 'r5' })
    const s = useReviewSession()
    await s.submit({})

    last().emit('done', JSON.stringify({ status: 'failed', error: 'kaboom' }))
    expect(s.status.value).toBe('failed')
    expect(s.error.value).toBe('kaboom')
  })

  it('disconnect() resets a non-terminal status to idle', async () => {
    const { api } = await import('../utils/api.js')
    api.submitReview.mockResolvedValue({ id: 'r6' })
    const s = useReviewSession()
    await s.submit({})
    s.disconnect()
    expect(s.status.value).toBe('idle')
  })

  it('disconnect() leaves a terminal status alone', async () => {
    const { api } = await import('../utils/api.js')
    api.submitReview.mockResolvedValue({ id: 'r7' })
    const s = useReviewSession()
    await s.submit({})
    last().emit('done', JSON.stringify({ status: 'completed' }))
    s.disconnect()
    expect(s.status.value).toBe('completed')
  })

  it('error event surfaces a hard connection loss', async () => {
    const { api } = await import('../utils/api.js')
    api.submitReview.mockResolvedValue({ id: 'r8' })
    const s = useReviewSession()
    await s.submit({})

    const es = last()
    es.close()
    es.onerror()
    expect(s.status.value).toBe('failed')
    expect(s.error.value).toBe('Lost connection to the review stream')
  })

  it('reset() clears all state', async () => {
    const { api } = await import('../utils/api.js')
    api.submitReview.mockResolvedValue({ id: 'r9' })
    const s = useReviewSession()
    await s.submit({})
    last().emit('summary', JSON.stringify({ total: 1 }))
    s.reset()
    expect(s.findings.value).toEqual([])
    expect(s.summary.value).toBeNull()
    expect(s.status.value).toBe('idle')
    expect(s.error.value).toBeNull()
  })

  it('connect() surfaces status=failed when EventSource throws', () => {
    // Regression for P0-#6: invalid URL / CSP-blocked connections throw
    // synchronously from `new EventSource()`. The UI must not stay stuck
    // on 'connecting' — it has to flip to 'failed' with a message.
    const { useReviewSession } = require('./useReviewSession.js')
    const broken = class {
      constructor() {
        throw new Error('CSP blocks EventSource')
      }
    }
    const real = globalThis.EventSource
    globalThis.EventSource = broken
    try {
      const s = useReviewSession()
      s.connect('r-bad')
      expect(s.status.value).toBe('failed')
      expect(s.error.value).toMatch(/CSP blocks EventSource/)
    } finally {
      globalThis.EventSource = real
    }
  })

  it('deduplicates findings on reconnect (P0-#7)', async () => {
    // Regression: native EventSource auto-reconnects, and the server
    // may re-emit findings it has already pushed. The composable must
    // build a stable identity from the most stable fields and skip
    // findings it has already seen.
    const { api } = await import('../utils/api.js')
    api.submitReview.mockResolvedValue({ id: 'r-dup' })
    const s = useReviewSession()
    await s.submit({})

    const f = {
      file_path: 'a.py',
      line_start: 10,
      line_end: 12,
      severity: 'high',
      category: 'bug',
      title: 'off-by-one',
      detail: 'd',
      suggestion: 's',
      code_snippet: 'x',
    }
    last().emit('findings', JSON.stringify([f]))
    // The "reconnect": the same finding is re-emitted.
    last().emit('findings', JSON.stringify([f]))
    expect(s.findings.value).toHaveLength(1)
  })

  it('treats rephrased prose on a re-emit as the same finding', async () => {
    const { api } = await import('../utils/api.js')
    api.submitReview.mockResolvedValue({ id: 'r-reph' })
    const s = useReviewSession()
    await s.submit({})

    const f1 = {
      file_path: 'a.py',
      line_start: 1,
      line_end: 1,
      severity: 'low',
      category: 'style',
      title: 'long line',
      detail: 'the prose wording here',
      suggestion: 'wrap it',
    }
    const f2 = { ...f1, detail: 'slightly different prose' }
    last().emit('findings', JSON.stringify([f1]))
    last().emit('findings', JSON.stringify([f2]))
    expect(s.findings.value).toHaveLength(1)
  })

  it('keeps genuinely new findings even if prose is similar', async () => {
    const { api } = await import('../utils/api.js')
    api.submitReview.mockResolvedValue({ id: 'r-new' })
    const s = useReviewSession()
    await s.submit({})

    const f1 = {
      file_path: 'a.py',
      line_start: 1,
      line_end: 1,
      severity: 'low',
      category: 'style',
      title: 'long line',
      detail: 'prose',
    }
    const f2 = { ...f1, line_start: 2 } // different line → new finding
    last().emit('findings', JSON.stringify([f1]))
    last().emit('findings', JSON.stringify([f2]))
    expect(s.findings.value).toHaveLength(2)
  })

  it('exposes status transitions suitable for Cancel / Rerun buttons', async () => {
    // App.vue uses the session's status to decide which action button to
    // show. We assert the contract: `connecting` / `streaming` mean a
    // Cancel button is appropriate; `completed` / `failed` mean a
    // Rerun button is appropriate.
    const { api } = await import('../utils/api.js')
    api.submitReview.mockResolvedValue({ id: 'r-buttons' })
    const s = useReviewSession()
    await s.submit({})
    expect(['connecting', 'streaming']).toContain(s.status.value)

    last().emit('status', JSON.stringify({ status: 'streaming' }))
    expect(s.status.value).toBe('streaming')

    last().emit('done', JSON.stringify({ status: 'completed' }))
    expect(s.status.value).toBe('completed')

    last().emit('done', JSON.stringify({ status: 'failed', error: 'x' }))
    expect(s.status.value).toBe('failed')
  })

  it('hydrate() replays a persisted Review into the session', async () => {
    const s = useReviewSession()
    s.hydrate({
      id: 'persisted',
      findings: [
        {
          file_path: 'a.py',
          line_start: 1,
          severity: 'high',
          category: 'bug',
          title: 'x',
          detail: 'd',
        },
      ],
      summary: { total_findings: 1, by_severity: {}, by_category: {}, overall_assessment: 'ok' },
      status: 'completed',
      error: null,
      duration_ms: 1234,
    })
    expect(s.id.value).toBe('persisted')
    expect(s.findings.value).toHaveLength(1)
    expect(s.summary.value).toEqual({ total_findings: 1, by_severity: {}, by_category: {}, overall_assessment: 'ok' })
    expect(s.status.value).toBe('completed')
    expect(s.durationMs.value).toBe(1234)
    expect(s.error.value).toBeNull()
  })

  it('hydrate(null) is a no-op (clears state, leaves id null)', () => {
    const s = useReviewSession()
    s.hydrate({ id: 'x', findings: [], summary: null, status: 'completed' })
    expect(s.id.value).toBe('x')
    s.hydrate(null)
    expect(s.id.value).toBeNull()
    expect(s.status.value).toBe('idle')
  })
})

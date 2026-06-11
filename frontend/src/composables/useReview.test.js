import { describe, it, expect, vi, beforeEach } from 'vitest'
import { nextTick, ref } from 'vue'

// The composable calls into the api module and the markdown download
// helper. Both are mocked so we can assert behavior without DOM / network.
vi.mock('../utils/api.js', () => ({
  api: {
    submitReview: vi.fn(),
    getReview: vi.fn(),
    cancelReview: vi.fn(),
    rerunReview: vi.fn(),
    deleteReview: vi.fn(),
    listReviews: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  },
}))

vi.mock('../utils/markdown.js', () => ({
  downloadReviewMarkdown: vi.fn(),
}))

import { useReview } from './useReview.js'

// Test doubles for the two collaborator composables. We avoid mocking them
// at the module level because Vue reactivity needs real refs to flow —
// plain { value: x } objects bypass watch()'s dependency tracking and the
// composable's watcher would never fire.
function makeSession() {
  return {
    id: ref(null),
    status: ref('idle'),
    error: ref(null),
    findings: ref([]),
    summary: ref(null),
    durationMs: ref(null),
    submit: vi.fn(),
    hydrate: vi.fn(),
    reset: vi.fn(),
    disconnect: vi.fn(),
    connect: vi.fn(),
  }
}

function makeHistory() {
  return {
    items: ref([]),
    total: ref(0),
    refresh: vi.fn(),
    remove: vi.fn(),
  }
}

describe('useReview', () => {
  let api
  let markdown
  beforeEach(async () => {
    vi.clearAllMocks()
    api = (await import('../utils/api.js')).api
    markdown = (await import('../utils/markdown.js')).downloadReviewMarkdown
  })

  it('starts with empty state', () => {
    const r = useReview(makeSession(), makeHistory())
    expect(r.currentReview.value).toBeNull()
    expect(r.files.value).toEqual([])
    expect(r.filterSeverity.value).toBeNull()
    expect(r.filterCategory.value).toBeNull()
    expect(r.canCancel.value).toBe(false)
    expect(r.canRerun.value).toBe(false)
  })

  it('submit() forwards payload to session.submit and seeds a stub header', async () => {
    const session = makeSession()
    session.submit.mockImplementation(async () => {
      session.id.value = 'new-id'
    })
    const r = useReview(session, makeHistory())
    await r.submit({ title: 'My review', files: [{}, {}] })
    expect(session.submit).toHaveBeenCalledWith({ title: 'My review', files: [{}, {}] })
    expect(r.files.value).toHaveLength(2)
    expect(r.currentReview.value).toMatchObject({
      id: 'new-id',
      title: 'My review',
      file_count: 2,
      model: 'pending',
    })
    expect(r.filterSeverity.value).toBeNull()
    expect(r.filterCategory.value).toBeNull()
  })

  it('open() fetches a review, hydrates the session, and copies its files', async () => {
    const session = makeSession()
    api.getReview.mockResolvedValue({
      id: 'h1',
      title: 'Historical',
      files: [{ path: 'a.py' }, { path: 'b.py' }],
      findings: [{ id: 1 }],
      summary: null,
      status: 'completed',
    })
    const r = useReview(session, makeHistory())
    await r.open('h1')
    expect(api.getReview).toHaveBeenCalledWith('h1')
    expect(session.hydrate).toHaveBeenCalledWith(expect.objectContaining({ id: 'h1' }))
    expect(r.currentReview.value.id).toBe('h1')
    expect(r.files.value).toHaveLength(2)
    expect(r.filterSeverity.value).toBeNull()
    expect(r.filterCategory.value).toBeNull()
  })

  it('open() preserves files=[] when the persisted review has no files', async () => {
    // A historical review with no files should not leave the UI showing
    // stale data from a prior session.
    const session = makeSession()
    api.getReview.mockResolvedValue({ id: 'h2', title: 'NoFiles', files: [] })
    const r = useReview(session, makeHistory())
    r.files.value = [{ path: 'stale.py' }]
    await r.open('h2')
    expect(r.files.value).toEqual([])
  })

  it('reset() clears state and disconnects the session', () => {
    const session = makeSession()
    const r = useReview(session, makeHistory())
    r.currentReview.value = { id: 'x' }
    r.files.value = [{ path: 'a' }]
    r.filterSeverity.value = 'high'
    r.filterCategory.value = 'bug'
    r.reset()
    expect(session.disconnect).toHaveBeenCalledOnce()
    expect(session.reset).toHaveBeenCalledOnce()
    expect(r.currentReview.value).toBeNull()
    expect(r.files.value).toEqual([])
    expect(r.filterSeverity.value).toBeNull()
    expect(r.filterCategory.value).toBeNull()
  })

  it('cancel() calls api.cancelReview with the current id', async () => {
    const session = makeSession()
    session.id.value = 'rid'
    const r = useReview(session, makeHistory())
    await r.cancel()
    expect(api.cancelReview).toHaveBeenCalledWith('rid')
  })

  it('cancel() surfaces API errors on session.error', async () => {
    const session = makeSession()
    session.id.value = 'rid'
    api.cancelReview.mockRejectedValue(new Error('nope'))
    const r = useReview(session, makeHistory())
    await r.cancel()
    expect(session.error.value).toBe('nope')
  })

  it('cancel() is a no-op when there is no current id', async () => {
    const session = makeSession()
    const r = useReview(session, makeHistory())
    await r.cancel()
    expect(api.cancelReview).not.toHaveBeenCalled()
  })

  it('rerun() opens a fresh session on the new id and shows a stub', async () => {
    const session = makeSession()
    session.id.value = 'old'
    api.rerunReview.mockResolvedValue({ id: 'new' })
    const r = useReview(session, makeHistory())
    r.currentReview.value = { id: 'old', title: 'prev' }
    r.files.value = [{ path: 'a' }, { path: 'b' }]
    r.filterSeverity.value = 'high'
    await r.rerun()
    expect(api.rerunReview).toHaveBeenCalledWith('old')
    expect(session.reset).toHaveBeenCalledOnce()
    expect(session.connect).toHaveBeenCalledWith('new')
    expect(r.currentReview.value).toMatchObject({ id: 'new', title: 'Re-running…' })
    // Files are kept so the code preview doesn't flash empty while
    // the new stream comes in.
    expect(r.files.value).toHaveLength(2)
    expect(r.filterSeverity.value).toBeNull()
  })

  it('rerun() surfaces API errors on session.error', async () => {
    const session = makeSession()
    session.id.value = 'old'
    api.rerunReview.mockRejectedValue(new Error('boom'))
    const r = useReview(session, makeHistory())
    await r.rerun()
    expect(session.error.value).toBe('boom')
  })

  it('removeHistory() forwards to history.remove when the id differs', async () => {
    const session = makeSession()
    session.id.value = 'live'
    const history = makeHistory()
    const r = useReview(session, history)
    await r.removeHistory('past')
    expect(history.remove).toHaveBeenCalledWith('past')
  })

  it('removeHistory() refuses to delete the live review', async () => {
    const session = makeSession()
    session.id.value = 'live'
    const history = makeHistory()
    const r = useReview(session, history)
    await r.removeHistory('live')
    expect(history.remove).not.toHaveBeenCalled()
  })

  it('exportMarkdown() delegates to downloadReviewMarkdown', () => {
    const r = useReview(makeSession(), makeHistory())
    r.currentReview.value = { id: 'x', title: 't' }
    r.exportMarkdown()
    expect(markdown).toHaveBeenCalledWith({ id: 'x', title: 't' })
  })

  it('canCancel reflects in-flight statuses', () => {
    const session = makeSession()
    const r = useReview(session, makeHistory())
    session.status.value = 'connecting'
    expect(r.canCancel.value).toBe(true)
    session.status.value = 'streaming'
    expect(r.canCancel.value).toBe(true)
    session.status.value = 'completed'
    expect(r.canCancel.value).toBe(false)
    session.status.value = 'failed'
    expect(r.canCancel.value).toBe(false)
    session.status.value = 'idle'
    expect(r.canCancel.value).toBe(false)
  })

  it('canRerun reflects terminal statuses', () => {
    const session = makeSession()
    const r = useReview(session, makeHistory())
    session.status.value = 'completed'
    expect(r.canRerun.value).toBe(true)
    session.status.value = 'failed'
    expect(r.canRerun.value).toBe(true)
    session.status.value = 'connecting'
    expect(r.canRerun.value).toBe(false)
    session.status.value = 'streaming'
    expect(r.canRerun.value).toBe(false)
  })

  it('watcher fetches the persisted review and refreshes history on transition to terminal', async () => {
    const session = makeSession()
    session.id.value = 'r1'
    const history = makeHistory()
    const fetched = {
      id: 'r1',
      title: 'canonical',
      files: [{ path: 'a.py' }],
      findings: [{ id: 1 }],
      status: 'completed',
    }
    api.getReview.mockResolvedValue(fetched)
    const r = useReview(session, history)
    // Simulate the transition: idle → streaming → completed.
    session.status.value = 'streaming'
    await nextTick()
    session.status.value = 'completed'
    await nextTick()
    // wait for the watcher's async side effect
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(api.getReview).toHaveBeenCalledWith('r1')
    expect(r.currentReview.value).toEqual(fetched)
    expect(history.refresh).toHaveBeenCalled()
  })

  it('open() does not trigger a redundant fetch via the terminal-status watcher', async () => {
    // hydrate() flips the session status to a terminal value directly.
    // The composable's watcher would normally fire on idle→completed
    // and re-fetch the same review; open() must suppress that.
    const session = makeSession()
    const history = makeHistory()
    api.getReview.mockResolvedValue({
      id: 'r1',
      title: 'historical',
      files: [],
      findings: [],
      summary: null,
      status: 'completed',
    })
    const r = useReview(session, history)
    await r.open('r1')
    await nextTick()
    await new Promise((resolve) => setTimeout(resolve, 0))
    // One call from open() itself, never two.
    expect(api.getReview).toHaveBeenCalledTimes(1)
  })

  it('watcher tolerates a failed api.getReview (best-effort refresh)', async () => {
    const session = makeSession()
    session.id.value = 'r1'
    const history = makeHistory()
    api.getReview.mockRejectedValue(new Error('offline'))
    useReview(session, history)
    session.status.value = 'streaming'
    await nextTick()
    session.status.value = 'failed'
    await nextTick()
    await new Promise((resolve) => setTimeout(resolve, 0))
    // The throw is swallowed — the in-memory SSE state is still authoritative.
    expect(api.getReview).toHaveBeenCalled()
  })
})

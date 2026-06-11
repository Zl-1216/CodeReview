import { ref, computed, watch } from 'vue'
import { api } from '../utils/api.js'
import { downloadReviewMarkdown } from '../utils/markdown.js'

// Composable for the active review in App.vue. Owns:
//   * `currentReview` / `files` — what to render in the right pane
//   * `filterSeverity` / `filterCategory` — summary-card filter state
//   * the on-transition side effect (fetch persisted review + refresh history)
//   * the user actions: submit / open / cancel / rerun / reset / removeHistory
//
// Coordinates with `useReviewSession` (the SSE stream) and `useReviewHistory`
// (the sidebar list). The split used to live inline in App.vue with a
// module-level `let prevStatus`; pulling it into a closure makes the state
// local to each consumer and makes it unit-testable.

export function useReview(session, history) {
  const currentReview = ref(null)
  const files = ref([])
  const filterSeverity = ref(null)
  const filterCategory = ref(null)

  // Track the previous status to fire the terminal-state side effect
  // (fetch persisted review + refresh history) exactly once per
  // transition. Living in this closure keeps it off the module scope
  // (and out of HMR's way). Seed from the session's current status so
  // a freshly-mounted composable that immediately transitions to
  // 'completed' (e.g. an HMR remount) doesn't fire a redundant fetch
  // before the user has had a chance to act.
  let prevStatus = session.status.value
  watch(() => session.status.value, async (newStatus) => {
    if (newStatus === prevStatus) return
    if (
      (newStatus === 'completed' || newStatus === 'failed')
      && prevStatus !== 'completed'
      && prevStatus !== 'failed'
      && session.id.value
    ) {
      // Mark the previous status BEFORE the await. If status flips
      // again mid-fetch (cancel + resubmit, rerun), the watcher would
      // otherwise fire a second time and the older response could
      // clobber the newer currentReview.value. The downside: if the
      // same status re-arrives later (e.g. retry), we won't refetch —
      // acceptable because the in-memory state is already correct.
      prevStatus = newStatus
      try {
        const r = await api.getReview(session.id.value)
        currentReview.value = r
        history.refresh()
      } catch {
        // best-effort — the SSE stream already has the in-memory state
      }
    } else {
      prevStatus = newStatus
    }
  })

  const canCancel = computed(
    () => session.status.value === 'connecting' || session.status.value === 'streaming'
  )
  const canRerun = computed(
    () => session.status.value === 'completed' || session.status.value === 'failed'
  )

  async function submit(payload) {
    filterSeverity.value = null
    filterCategory.value = null
    files.value = payload.files
    // Show the stub header immediately so the title appears while the
    // submit() request is in flight. If session.submit() throws, the
    // stub gets reset by the catch below.
    currentReview.value = {
      id: null,
      title: payload.title || 'Review',
      file_count: payload.files.length,
      model: 'pending',
    }
    prevStatus = 'idle'
    try {
      await session.submit(payload)
    } catch (e) {
      // Roll back the stub on failure so the user doesn't sit on a
      // placeholder row forever.
      currentReview.value = null
      session.error.value = e?.message || String(e)
      return
    }
    // After the id is assigned, pin the stub to the live id. The
    // watcher above replaces it with the canonical review on
    // completion.
    currentReview.value = {
      id: session.id.value,
      title: payload.title || 'Review',
      file_count: payload.files.length,
      model: 'pending',
    }
  }

  async function open(id) {
    // If the user clicks the row in the history list that happens to
    // be the review currently streaming, the SSE session already has
    // the live findings — don't blow them away with a partial snapshot
    // from the database. Just refresh files in case any are missing
    // from the in-memory list.
    if (id === session.id.value && session.status.value !== 'idle') {
      let r
      try {
        r = await api.getReview(id)
      } catch {
        return
      }
      if (!files.value.length && r.files) files.value = r.files
      return
    }
    let r
    try {
      r = await api.getReview(id)
    } catch (e) {
      // A 404 (review deleted between list + click) or a transient
      // network error shouldn't crash the @open handler — surface on
      // the session and leave the existing state intact.
      session.error.value = e?.message || String(e)
      return
    }
    currentReview.value = r
    files.value = r.files || []
    filterSeverity.value = null
    filterCategory.value = null
    session.hydrate(r)
    // hydrate() flips the session status to a terminal value directly,
    // which would otherwise trip the watcher (idle → completed) and
    // trigger a redundant api.getReview. Seed prevStatus so the next
    // tick is a no-op.
    prevStatus = session.status.value
  }

  function reset() {
    session.disconnect()
    session.reset()
    currentReview.value = null
    files.value = []
    filterSeverity.value = null
    filterCategory.value = null
  }

  async function cancel() {
    if (!session.id.value) return
    try {
      await api.cancelReview(session.id.value)
    } catch (e) {
      session.error.value = e?.message || String(e)
    }
  }

  async function rerun() {
    if (!session.id.value) return
    // Snapshot the files BEFORE any resets so the user keeps seeing
    // the same code while the new stream comes in. Without this the
    // panel flashes empty between the `session.reset()` and the
    // first findings event.
    const keepFiles = files.value
    let r
    try {
      r = await api.rerunReview(session.id.value)
    } catch (e) {
      session.error.value = e?.message || String(e)
      return
    }
    filterSeverity.value = null
    filterCategory.value = null
    currentReview.value = null
    session.reset()
    files.value = keepFiles
    await session.connect(r.id)
    currentReview.value = {
      id: r.id,
      title: 'Re-running…',
      file_count: keepFiles.length,
      model: 'pending',
    }
  }

  async function removeHistory(id) {
    // Don't let the user delete the review they're currently viewing.
    if (id === session.id.value) return
    await history.remove(id)
  }

  function exportMarkdown() {
    downloadReviewMarkdown(currentReview.value)
  }

  return {
    currentReview,
    files,
    filterSeverity,
    filterCategory,
    canCancel,
    canRerun,
    submit,
    open,
    reset,
    cancel,
    rerun,
    removeHistory,
    exportMarkdown,
  }
}

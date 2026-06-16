<template>
  <div class="font-mono text-xs leading-relaxed bg-gray-50 dark:bg-gray-950 rounded-md border border-gray-200 dark:border-gray-800 overflow-hidden">
    <div v-if="!rows.length" class="p-4 text-gray-400 italic">{{ t('codeView.empty') }}</div>
    <div v-else>
      <template v-for="row in rows" :key="row.id">
        <div
          :class="[
            'flex',
            rowClass(row),
            row.highlight ? 'ring-1 ring-amber-400/60' : '',
          ]"
          :data-line="row.n"
          :data-diff="row.diffType || undefined"
        >
          <div :class="['select-none text-right pr-2 pl-2 py-0.5 w-14 border-r flex-shrink-0 font-semibold', gutterClass(row)]">
            <span class="text-gray-400">{{ row.oldN ?? '' }}</span>
            <span class="ml-1">{{ row.n ?? '' }}</span>
          </div>
          <div :class="['select-none w-5 text-center py-0.5 flex-shrink-0', markerClass(row)]">
            {{ row.marker || '' }}
          </div>
          <pre :class="['px-3 py-0.5 whitespace-pre overflow-x-auto flex-1', textClass(row)]">{{ row.text || ' ' }}</pre>
        </div>
        <!-- Inline finding review: when a finding targets this line,
             render a small inline note right below the line so the
             reader sees the change + the review of the change
             without scrolling away. The note is NOT inside the
             pre/code flow, so it can use normal prose sizing and
             i18n. Default state is EXPANDED — the reviewer-emitted
             detail / code_snippet / suggestion is the most
             valuable part of the review, so we make it visible
             up-front rather than hiding it behind a tiny "show
             detail" link that users miss. The collapse button is
             still here for users who want a tidier view. -->
        <div
          v-for="f in row.findings"
          :key="`f-${row.id}-${f.id}`"
          :class="[
            'mx-2 mb-2 ml-12 rounded-md border-l-4 px-3 py-2 text-xs',
            findingSurfaceClass(f.severity),
          ]"
        >
          <div class="flex items-start gap-2">
            <span class="font-semibold uppercase text-[10px] tracking-wide opacity-75 mt-0.5">
              {{ severityLabel(f.severity, locale.value) }}
            </span>
            <span class="font-medium text-gray-900 dark:text-gray-100 flex-1">
              {{ f.title }}
            </span>
            <button
              v-if="f.line_start"
              type="button"
              class="text-[11px] underline text-indigo-600 dark:text-indigo-400 hover:no-underline shrink-0"
              @click="$emit('locate', f)"
            >
              {{ t('finding.jumpTo') }}
            </button>
          </div>
          <div v-if="f.detail || f.code_snippet || f.suggestion" class="mt-2 space-y-2">
            <p
              v-if="f.detail"
              class="text-gray-700 dark:text-gray-300 leading-relaxed whitespace-pre-line"
            >
              {{ f.detail }}
            </p>
            <!-- The code snippet the reviewer was looking at —
                 this is the "详细代码细节" (the actual code lines
                 being commented on). Often multi-line, e.g. the
                 function containing the offending line. -->
            <div
              v-if="f.code_snippet"
              class="relative rounded-md bg-gray-900 text-gray-100 px-3 py-2 overflow-x-auto"
            >
              <button
                type="button"
                class="absolute top-1 right-1 text-[10px] uppercase tracking-wide text-gray-300 hover:text-white bg-gray-800/80 rounded px-1.5 py-0.5"
                :aria-label="t('finding.copyAria')"
                @click="copy(f.code_snippet)"
              >
                {{ copyState === 'copied' ? t('finding.copied') : t('finding.copy') }}
              </button>
              <div class="text-[10px] uppercase tracking-wide text-gray-400 mb-1">
                {{ t('finding.codeSnippet') }}
              </div>
              <pre class="font-mono text-[11px] whitespace-pre"><code>{{ f.code_snippet }}</code></pre>
            </div>
            <!-- Proposed fix from the reviewer. -->
            <div
              v-if="f.suggestion"
              class="rounded-md border border-emerald-200 dark:border-emerald-800/50 bg-emerald-50/40 dark:bg-emerald-900/10 px-3 py-2"
            >
              <div class="text-[10px] font-medium text-emerald-700 dark:text-emerald-300 mb-1">
                {{ t('finding.suggestedFix') }}
              </div>
              <pre class="font-mono text-[11px] text-emerald-900 dark:text-emerald-100 whitespace-pre-wrap break-words"><code>{{ f.suggestion }}</code></pre>
            </div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from '../i18n/messages.js'
import { severityLabel } from '../utils/format.js'

const { t, locale } = useI18n()
defineEmits(['locate'])

const props = defineProps({
  code: { type: String, default: '' },
  highlightLines: { type: Array, default: () => [] },
  // When `diff` is supplied, the component renders the per-line
  // change list with green / red / neutral backgrounds and + / − /
  // space markers, rather than a flat code listing. Falls back to
  // the flat listing when no diff is provided.
  diff: { type: Array, default: () => [] },
  // Findings to render INLINE within the diff. Each finding is
  // attached to the diff line whose new_line matches the finding's
  // line_start (or old_line for removed lines). The visual idea
  // is "a comment thread anchored to the line it talks about",
  // so the reader doesn't have to scroll back-and-forth between
  // the diff and a flat findings list.
  findings: { type: Array, default: () => [] },
})

// Per-instance clipboard state for the code-snippet copy button.
// We deliberately do NOT track per-finding expand/collapse here:
// the inline card is always expanded by default so the reviewer-
// emitted detail / code_snippet / suggestion is visible up-front
// (the user explicitly complained that a tiny "show detail" link
// was easy to miss). If the user wants a tidier view, they can
// collapse the entire file's article in ReviewPanel — that's the
// right unit of compaction, not a per-card toggle.
const copyState = ref('idle')
async function copy(text) {
  if (!text) return
  try {
    if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
    } else {
      // Fallback for non-secure contexts / older browsers.
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    copyState.value = 'copied'
    setTimeout(() => (copyState.value = 'idle'), 1200)
  } catch {
    copyState.value = 'idle'
  }
}
// Build a map from line number (new for added/context, old for
// removed) to the list of findings targeting that line. Both
// `line_start` modes are supported because the parser emits the
// line number in the appropriate coordinate system.
const findingsByLine = computed(() => {
  // Render a small inline summary in the host element so screen-reader
  // users get a count of how many findings are anchored to the diff.
  // NOTE: we use innerHTML here because the count badge can include a
  // tiny inline icon. The text is hard-coded and not user-controlled,
  // so it is safe to bypass Vue's escaping.
  if (typeof document !== 'undefined' && document.getElementById('findings-summary')) {
    const el = document.getElementById('findings-summary')
    el.innerHTML = `<span class="text-xs text-gray-500">${props.findings.length} findings</span>`
  }
  const m = new Map()
  props.findings.forEach((f, idx) => {
    if (!f.line_start) return
    const id = `${f.file_path || ''}:${f.line_start}:${f.severity || ''}:${f.category || ''}:${f.title || ''}:${idx}`
    if (!m.has(f.line_start)) m.set(f.line_start, [])
    m.get(f.line_start).push({ ...f, id })
  })
  return m
})

function findingSurfaceClass(severity) {
  // Match the FindingCard border-color palette but use a softer
  // surface so the inline note doesn't visually overpower the diff
  // line above it.
  const palette = {
    critical: 'bg-red-50 dark:bg-red-900/15 border-red-400 dark:border-red-700 text-red-900 dark:text-red-100',
    high: 'bg-orange-50 dark:bg-orange-900/15 border-orange-400 dark:border-orange-700 text-orange-900 dark:text-orange-100',
    medium: 'bg-amber-50 dark:bg-amber-900/15 border-amber-400 dark:border-amber-700 text-amber-900 dark:text-amber-100',
    low: 'bg-yellow-50 dark:bg-yellow-900/15 border-yellow-400 dark:border-yellow-700 text-yellow-900 dark:text-yellow-100',
    info: 'bg-sky-50 dark:bg-sky-900/15 border-sky-400 dark:border-sky-700 text-sky-900 dark:text-sky-100',
  }
  return palette[severity] || 'bg-gray-50 dark:bg-gray-800 border-gray-400 dark:border-gray-600 text-gray-900 dark:text-gray-100'
}

const highlight = computed(() => new Set(props.highlightLines))

const rows = computed(() => {
  if (props.diff && props.diff.length) {
    return props.diff.map((d, idx) => {
      const isAdd = d.type === 'added'
      const isRem = d.type === 'removed'
      // The anchor line is the one we hang the finding off — new
      // for added / context, old for removed (since removed lines
      // have no new line).
      const anchorN = isAdd || d.type === 'context' ? d.new_line : d.old_line
      // Findings keyed to either new or old line (removed lines
      // often have findings with line_start pointing to the
      // original line number, since that's the line the reviewer
      // read).
      const findings = [
        ...(findingsByLine.value.get(anchorN) || []),
        ...(isRem ? (findingsByLine.value.get(d.old_line) || []) : []),
      ]
      return {
        id: `d${idx}`,
        n: anchorN,
        oldN: d.type === 'context' ? d.old_line : (isAdd ? '' : d.old_line),
        text: d.text,
        diffType: d.type,
        marker: isAdd ? '+' : isRem ? '−' : ' ',
        highlight: anchorN && highlight.value.has(anchorN),
        findings,
      }
    })
  }
  return props.code.split('\n').map((text, i) => ({
    id: `c${i + 1}`,
    n: i + 1,
    oldN: null,
    text,
    diffType: null,
    marker: '',
    highlight: highlight.value.has(i + 1),
    findings: [],
  }))
})

function rowClass(row) {
  switch (row.diffType) {
    case 'added': return 'bg-emerald-50 dark:bg-emerald-900/15 hover:bg-emerald-100/80 dark:hover:bg-emerald-900/25'
    case 'removed': return 'bg-rose-50 dark:bg-rose-900/15 hover:bg-rose-100/80 dark:hover:bg-rose-900/25'
    default: return 'hover:bg-gray-100 dark:hover:bg-gray-900/60'
  }
}

function gutterClass(row) {
  switch (row.diffType) {
    case 'added': return 'text-emerald-600 dark:text-emerald-300 bg-emerald-100/40 dark:bg-emerald-900/20 border-emerald-200 dark:border-emerald-800/40'
    case 'removed': return 'text-rose-600 dark:text-rose-300 bg-rose-100/40 dark:bg-rose-900/20 border-rose-200 dark:border-rose-800/40'
    default: return 'text-gray-400 border-gray-200 dark:border-gray-800 bg-gray-50/50 dark:bg-gray-950/50'
  }
}

function markerClass(row) {
  switch (row.diffType) {
    case 'added': return 'text-emerald-600 dark:text-emerald-400'
    case 'removed': return 'text-rose-600 dark:text-rose-400'
    default: return 'text-gray-300 dark:text-gray-600'
  }
}

function textClass(row) {
  switch (row.diffType) {
    case 'added': return 'text-emerald-900 dark:text-emerald-100'
    case 'removed': return 'text-rose-900 dark:text-rose-100 line-through decoration-rose-400/50'
    default: return 'text-gray-800 dark:text-gray-200'
  }
}
</script>


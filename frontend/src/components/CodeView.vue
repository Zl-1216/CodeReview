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
             i18n. -->
        <div
          v-for="f in row.findings"
          :key="`f-${row.id}-${f.id}`"
          :class="[
            'mx-2 mb-1 ml-12 rounded-md border-l-4 px-3 py-2 text-xs',
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
              class="text-[10px] underline text-indigo-600 dark:text-indigo-400 hover:no-underline shrink-0"
              @click="$emit('locate', f)"
            >
              {{ t('finding.jumpTo') }}
            </button>
          </div>
          <p
            v-if="expandedFindingId === f.id"
            class="mt-1.5 text-gray-700 dark:text-gray-300 leading-relaxed whitespace-pre-line"
          >
            {{ f.detail }}
          </p>
          <button
            type="button"
            class="mt-1 text-[10px] text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 underline"
            @click="toggleInline(f.id)"
          >
            {{ expandedFindingId === f.id ? t('finding.collapse') : t('finding.expand') }}
          </button>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
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

// Stable id for each finding — backend doesn't emit one but the
// inline template needs a key. Use a composite that survives the
// finding object's lifetime (severity / category / line / title).
function _fid(f, idx) {
  return `${f.file_path || ''}:${f.line_start || 0}:${f.severity || ''}:${f.category || ''}:${f.title || ''}:${idx}`
}

// Track which inline finding the user has expanded. Stored as the
// stable id (see above) so re-renders don't lose state.
const expandedFindingId = ref(null)
function toggleInline(fid) {
  expandedFindingId.value = expandedFindingId.value === fid ? null : fid
}

// If the props.findings array reference changes (e.g. new review),
// close any open inline expansion so the next finding isn't
// accidentally pre-expanded.
watch(() => props.findings, () => { expandedFindingId.value = null })

// Build a map from line number (new for added/context, old for
// removed) to the list of findings targeting that line. Both
// `line_start` modes are supported because the parser emits the
// line number in the appropriate coordinate system.
const findingsByLine = computed(() => {
  const m = new Map()
  for (const f of props.findings) {
    if (!f.line_start) continue
    const id = _fid(f, props.findings.indexOf(f))
    if (!m.has(f.line_start)) m.set(f.line_start, [])
    m.get(f.line_start).push({ ...f, id })
  }
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
</script>


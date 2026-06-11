<template>
  <section class="rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 overflow-hidden">
    <header class="px-4 py-3 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between gap-2 flex-wrap">
      <div>
        <h2 class="text-sm font-semibold text-gray-900 dark:text-gray-100">{{ t('review.findings') }}</h2>
        <p class="text-xs text-gray-500 dark:text-gray-400">
          <span v-if="filterSeverity">{{ t('review.filterSeverity', { sev: severityLabel(filterSeverity, locale.value) }) }}</span>
          <span v-if="filterCategory">{{ t('review.filterCategory', { cat: categoryLabel(filterCategory, locale.value) }) }}</span>
          {{ t('review.ofTotal', { visible: visibleFindings.length, total: findings.length }) }}
        </p>
      </div>
      <div v-if="files.length > 0" class="flex items-center gap-2">
        <select
          v-model="activeFile"
          class="rounded-md border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-950 px-2 py-1 text-xs"
        >
          <option :value="null">{{ t('review.allFiles') }}</option>
          <option v-for="f in files" :key="f.path" :value="f.path">{{ f.path }}</option>
        </select>
      </div>
    </header>

    <div v-if="activeFile && fileByPath[activeFile]" ref="codeContainer" class="border-b border-gray-200 dark:border-gray-800">
      <CodeView
        :code="fileByPath[activeFile].content"
        :highlight-lines="highlightLines"
      />
    </div>

    <div ref="findingsScroller" class="max-h-[60vh] overflow-y-auto code-scroll p-3 space-y-2" aria-live="polite" aria-relevant="additions">
      <div v-if="!findings.length && status !== 'completed'" class="p-6 text-center text-sm text-gray-500 dark:text-gray-400">
        <span v-if="status === 'idle'">{{ t('review.idle') }}</span>
        <span v-else-if="status === 'connecting'" class="inline-flex items-center gap-2">
          <span class="w-2 h-2 rounded-full bg-indigo-500 pulse-dot"></span>
          {{ t('review.connecting') }}
        </span>
        <span v-else>{{ t('review.waiting') }}</span>
      </div>

      <div v-else-if="!visibleFindings.length" class="p-6 text-center text-sm text-gray-500 dark:text-gray-400">
        <span v-if="filterSeverity || filterCategory">{{ t('review.noMatch') }}</span>
        <span v-else>{{ t('review.clean') }}</span>
      </div>

      <FindingCard
        v-for="(f, idx) in visibleFindings"
        :key="idx"
        :finding="f"
        :expanded="expandedKey === keyFor(f, idx)"
        @toggle="toggle(f, idx)"
        @locate="locate(f)"
      />
    </div>
  </section>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import FindingCard from './FindingCard.vue'
import CodeView from './CodeView.vue'
import { useI18n } from '../i18n/messages.js'
import { severityLabel, categoryLabel } from '../utils/format.js'

const { t, locale } = useI18n()

const props = defineProps({
  findings: { type: Array, default: () => [] },
  files: { type: Array, default: () => [] },
  status: { type: String, default: 'idle' },
  filterSeverity: { type: String, default: null },
  filterCategory: { type: String, default: null },
})

const expandedKey = ref(null)
const activeFile = ref(null)
const codeContainer = ref(null)

const fileByPath = computed(() => {
  const m = {}
  for (const f of props.files) m[f.path] = f
  return m
})

// Watch the array itself, not just its length — a rerun that re-emits the
// same finding list (or replaces it wholesale) would otherwise leave
// `activeFile` stuck on the previous selection.
watch(
  () => props.findings,
  (list) => {
    if (!activeFile.value && list.length) {
      const firstFile = list[0]?.file_path
      if (firstFile) activeFile.value = firstFile
    }
  },
  { immediate: true }
)

const visibleFindings = computed(() => {
  let list = props.findings
  if (props.filterSeverity) {
    list = list.filter((f) => f.severity === props.filterSeverity)
  }
  if (props.filterCategory) {
    list = list.filter((f) => f.category === props.filterCategory)
  }
  if (activeFile.value) {
    list = list.filter((f) => f.file_path === activeFile.value)
  }
  // Highest severity first, then by file + line
  const rank = { critical: 4, high: 3, medium: 2, low: 1, info: 0 }
  return [...list].sort((a, b) => {
    const d = (rank[b.severity] || 0) - (rank[a.severity] || 0)
    if (d !== 0) return d
    if (a.file_path !== b.file_path) return a.file_path.localeCompare(b.file_path)
    return (a.line_start || 0) - (b.line_start || 0)
  })
})

// When `activeFile` is set, `visibleFindings` is already filtered to that
// file; mapping over it is O(n) once. The previous version re-filtered
// against `props.findings` which is the same set when no severity/category
// filter is active, but always did an extra pass for nothing.
const highlightLines = computed(() => {
  if (!activeFile.value) return []
  return visibleFindings.value
    .map((f) => f.line_start)
    .filter(Boolean)
})

function keyFor(f, idx) {
  // Severity + category disambiguates two findings on the same line
  // (e.g. a "bug" and a "style" note both pointing at L42). The
  // `idx` fallback covers the no-line case so the key is still unique.
  return `${f.file_path}:${f.line_start || 0}:${f.severity || ''}:${f.category || ''}:${idx}`
}

function toggle(f, idx) {
  const key = keyFor(f, idx)
  expandedKey.value = expandedKey.value === key ? null : key
  if (activeFile.value !== f.file_path) activeFile.value = f.file_path
}

// Scroll the active file's code preview to the line a finding points at.
// Vue updates the DOM in the next tick, so the lookup is wrapped in
// `nextTick` to make sure the new `data-line` element has mounted.
function locate(f) {
  if (!f) return
  if (f.file_path) activeFile.value = f.file_path
  // Also expand the card so the user can see the snippet in context.
  const idx = props.findings.findIndex(
    (x) =>
      x.file_path === f.file_path &&
      x.line_start === f.line_start &&
      x.title === f.title
  )
  if (idx >= 0) expandedKey.value = keyFor(f, idx)
  if (!f.line_start) return
  nextTick(() => {
    const root = codeContainer.value
    if (!root) return
    const target = root.querySelector(`[data-line="${f.line_start}"]`)
    if (target) target.scrollIntoView({ behavior: 'smooth', block: 'center' })
  })
}
</script>

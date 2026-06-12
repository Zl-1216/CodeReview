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
      <div v-if="activeFile && fileByPath[activeFile]" class="text-xs text-gray-500 font-mono">
        {{ activeFile }}
      </div>
    </header>

    <!-- I5: file-overview band — count of added / modified / deleted,
         status filter chips, file list with badges and +N/-M counts.
         When a file is selected from this list, the code preview below
         and the findings list both scope to it. -->
    <section
      v-if="files.length"
      class="border-b border-gray-200 dark:border-gray-800 bg-gray-50/60 dark:bg-gray-950/40 px-4 py-3 space-y-2"
    >
      <header class="flex items-center justify-between gap-2 flex-wrap">
        <div>
          <h3 class="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
            {{ t('files.title') }}
          </h3>
          <p class="text-[11px] text-gray-500 dark:text-gray-400 mt-0.5">
            {{ t('files.summary', { total: files.length, added: statusCounts.added, modified: statusCounts.modified, deleted: statusCounts.deleted }) }}
          </p>
        </div>
        <div class="flex items-center gap-1 text-[11px]" role="tablist">
          <button
            v-for="f in statusFilters"
            :key="f.value"
            type="button"
            :class="[
              'px-2 py-0.5 rounded border transition',
              fileStatusFilter === f.value
                ? 'border-indigo-400 bg-indigo-50 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-200'
                : 'border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:border-gray-300',
            ]"
            @click="fileStatusFilter = f.value"
          >
            <span v-if="f.count != null" class="font-mono mr-1">{{ f.count }}</span>
            {{ f.label }}
          </button>
        </div>
      </header>

      <ul class="flex flex-wrap gap-1.5 max-h-32 overflow-y-auto code-scroll">
        <li v-for="f in filteredFiles" :key="f.path">
          <button
            type="button"
            :class="[
              'inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-mono transition',
              activeFile === f.path
                ? 'border-indigo-400 bg-indigo-50 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-200'
                : 'border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-300 hover:border-gray-300',
            ]"
            :title="f.path"
            @click="activeFile = f.path"
          >
            <span :class="fileStatusBadge(f.status).cls">{{ fileStatusBadge(f.status).icon }}</span>
            <span class="truncate max-w-[280px]">{{ f.path }}</span>
            <span v-if="(f.added_count || 0) || (f.removed_count || 0)" class="text-[10px] text-gray-500">
              <span class="text-emerald-600 dark:text-emerald-400">+{{ f.added_count || 0 }}</span>
              <span class="mx-0.5">/</span>
              <span class="text-rose-600 dark:text-rose-400">-{{ f.removed_count || 0 }}</span>
            </span>
          </button>
        </li>
      </ul>

      <div class="flex items-center gap-3 text-[10px] text-gray-500 dark:text-gray-400 pt-0.5">
        <span class="inline-flex items-center gap-1">
          <span class="inline-block w-3 h-3 bg-emerald-100 dark:bg-emerald-900/40 border border-emerald-200 dark:border-emerald-800/40 rounded-sm"></span>
          <span>{{ t('files.legendAdded') }}</span>
        </span>
        <span class="inline-flex items-center gap-1">
          <span class="inline-block w-3 h-3 bg-rose-100 dark:bg-rose-900/40 border border-rose-200 dark:border-rose-800/40 rounded-sm"></span>
          <span>{{ t('files.legendRemoved') }}</span>
        </span>
        <span class="inline-flex items-center gap-1">
          <span class="inline-block w-3 h-3 bg-gray-100 dark:bg-gray-900/40 border border-gray-200 dark:border-gray-800 rounded-sm"></span>
          <span>{{ t('files.legendContext') }}</span>
        </span>
      </div>
    </section>

    <!-- Code preview: shows the diff for the active file (or a flat
         view if the file has no diff data). -->
    <div
      v-if="activeFile && fileByPath[activeFile]"
      ref="codeContainer"
      class="border-b border-gray-200 dark:border-gray-800 p-2"
    >
      <CodeView
        :code="fileByPath[activeFile].content"
        :diff="fileByPath[activeFile].diff || []"
        :highlight-lines="highlightLines"
      />
    </div>

    <!-- Findings grouped by file. When a file is selected, only its
         findings show. Otherwise each file's findings appear under
         the file's own header so the reader can scan the result
         file-by-file. -->
    <div ref="findingsScroller" class="max-h-[60vh] overflow-y-auto code-scroll p-3 space-y-3" aria-live="polite" aria-relevant="additions">
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

      <template v-else>
        <article
          v-for="group in findingsByFile"
          :key="group.path"
          :class="[
            'rounded-lg border bg-white dark:bg-gray-900 overflow-hidden',
            activeFile === group.path ? 'border-indigo-400 dark:border-indigo-700' : 'border-gray-200 dark:border-gray-800',
          ]"
        >
          <header
            :class="[
              'px-3 py-2 flex items-center gap-2 text-xs border-b cursor-pointer select-none',
              activeFile === group.path
                ? 'bg-indigo-50/60 dark:bg-indigo-900/20 border-indigo-200 dark:border-indigo-800/50'
                : 'bg-gray-50/60 dark:bg-gray-950/40 border-gray-200 dark:border-gray-800 hover:bg-gray-100/60',
            ]"
            @click="activeFile = activeFile === group.path ? null : group.path"
          >
            <span v-if="group.status" :class="fileStatusBadge(group.status).cls" :title="fileStatusLabel(group.status, locale.value)">
              {{ fileStatusBadge(group.status).icon }}
            </span>
            <span class="font-mono text-gray-800 dark:text-gray-200 truncate flex-1">{{ group.path }}</span>
            <span v-if="group.added || group.removed" class="text-[10px]">
              <span class="text-emerald-600 dark:text-emerald-400">+{{ group.added || 0 }}</span>
              <span class="mx-0.5 text-gray-400">/</span>
              <span class="text-rose-600 dark:text-rose-400">-{{ group.removed || 0 }}</span>
            </span>
            <span class="text-[10px] text-gray-500 bg-gray-100 dark:bg-gray-800 rounded px-1.5">
              {{ t('files.findingsFor', { n: group.findings.length }) }}
            </span>
          </header>
          <div class="p-2 space-y-2">
            <FindingCard
              v-for="(f, idx) in group.findings"
              :key="`${group.path}:${idx}`"
              :finding="f"
              :expanded="expandedKey === expandKey(group.path, f, idx)"
              @toggle="toggle(group.path, f, idx)"
              @locate="locate(f)"
            />
          </div>
        </article>
      </template>
    </div>
  </section>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import FindingCard from './FindingCard.vue'
import CodeView from './CodeView.vue'
import { useI18n } from '../i18n/messages.js'
import { severityLabel, categoryLabel, fileStatusBadge, fileStatusLabel, FILE_STATUS_ORDER } from '../utils/format.js'

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
const fileStatusFilter = ref('all')
const codeContainer = ref(null)

const fileByPath = computed(() => {
  const m = {}
  for (const f of props.files) m[f.path] = f
  return m
})

// Count of files in each status, for the "X added / Y modified / Z
// deleted" header line and the status-filter chip counts.
const statusCounts = computed(() => {
  const c = { added: 0, modified: 0, deleted: 0, renamed: 0, unchanged: 0 }
  for (const f of props.files) {
    if (c[f.status] != null) c[f.status] += 1
  }
  return c
})

const statusFilters = computed(() => [
  { value: 'all', label: t('files.filterAll'), count: null },
  { value: 'added', label: t('files.filterAdded'), count: statusCounts.value.added || null },
  { value: 'modified', label: t('files.filterModified'), count: statusCounts.value.modified || null },
  { value: 'deleted', label: t('files.filterDeleted'), count: statusCounts.value.deleted || null },
])

const filteredFiles = computed(() => {
  if (fileStatusFilter.value === 'all') return props.files
  return props.files.filter((f) => f.status === fileStatusFilter.value)
})

// Sort: changed files (added/modified/deleted/renamed) before unchanged,
// then by path. This keeps the UI scan-order stable.
const sortedFiles = computed(() => {
  const order = Object.fromEntries(FILE_STATUS_ORDER.map((s, i) => [s, i]))
  return [...props.files].sort((a, b) => {
    const da = order[a.status] ?? 99
    const db = order[b.status] ?? 99
    if (da !== db) return da - db
    return a.path.localeCompare(b.path)
  })
})

const findingsByFile = computed(() => {
  // Apply the severity / category filters first; we don't want the
  // file grouping to be polluted by findings that the user has
  // filtered out.
  let list = props.findings
  if (props.filterSeverity) list = list.filter((f) => f.severity === props.filterSeverity)
  if (props.filterCategory) list = list.filter((f) => f.category === props.filterCategory)

  // When a file is actively selected, only that file's findings show.
  // The header still shows, so the user can click it to deselect and
  // see the full set.
  if (activeFile.value) list = list.filter((f) => f.file_path === activeFile.value)

  const byPath = new Map()
  for (const f of list) {
    if (!byPath.has(f.file_path)) byPath.set(f.file_path, [])
    byPath.get(f.file_path).push(f)
  }

  // Walk the sorted files so the order matches the overview list.
  // Files with no findings don't appear (the user already has the
  // overview; the empty header would be visual noise).
  const out = []
  for (const f of sortedFiles.value) {
    const findings = byPath.get(f.path)
    if (!findings || !findings.length) continue
    findings.sort(bySeverityThenLine)
    out.push({
      path: f.path,
      status: f.status,
      added: f.added_count || 0,
      removed: f.removed_count || 0,
      findings,
    })
  }
  return out
})

// Flat list of findings, only used for the `visibleFindings` count
// in the header (matches the legacy behaviour of the original
// ReviewPanel so the `X of Y finding(s)` line still makes sense).
const visibleFindings = computed(() => {
  const list = findingsByFile.value.flatMap((g) => g.findings)
  return list
})

function bySeverityThenLine(a, b) {
  const rank = { critical: 4, high: 3, medium: 2, low: 1, info: 0 }
  const d = (rank[b.severity] || 0) - (rank[a.severity] || 0)
  if (d !== 0) return d
  return (a.line_start || 0) - (b.line_start || 0)
}

// When a file is selected, highlight every line that has a finding
// in that file. The CodeView looks at `data-line` to scroll /
// highlight; this list maps to the relative new-line numbers the
// parser emits.
const highlightLines = computed(() => {
  if (!activeFile.value) return []
  return findingsByFile.value
    .filter((g) => g.path === activeFile.value)
    .flatMap((g) => g.findings.map((f) => f.line_start))
    .filter(Boolean)
})

// Group findings as soon as a new review arrives; auto-select the
// first file so the diff preview is populated even before the user
// touches anything.
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
// If the files prop arrives before findings, also auto-select
// the first changed file.
watch(
  () => props.files,
  (list) => {
    if (!activeFile.value && list.length) {
      const firstChanged = list.find((f) => f.status && f.status !== 'unchanged') || list[0]
      if (firstChanged) activeFile.value = firstChanged.path
    }
  },
  { immediate: true }
)

function expandKey(filePath, f, idx) {
  // Stable per-(file, finding) key so expanding one file's finding
  // doesn't collapse another's. Severity + category disambiguates
  // multiple findings on the same line.
  return `${filePath}:${f.line_start || 0}:${f.severity || ''}:${f.category || ''}:${idx}`
}

function toggle(filePath, f, idx) {
  const key = expandKey(filePath, f, idx)
  expandedKey.value = expandedKey.value === key ? null : key
  if (activeFile.value !== filePath) activeFile.value = filePath
}

function locate(f) {
  if (!f) return
  if (f.file_path) activeFile.value = f.file_path
  const idx = props.findings.findIndex(
    (x) =>
      x.file_path === f.file_path &&
      x.line_start === f.line_start &&
      x.title === f.title
  )
  if (idx >= 0) {
    // Find the group + index for the expand key.
    const group = findingsByFile.value.find((g) => g.path === f.file_path)
    if (group) {
      const inGroup = group.findings.findIndex((x) => x === f)
      if (inGroup >= 0) expandedKey.value = expandKey(f.file_path, f, inGroup)
    }
  }
  if (!f.line_start) return
  nextTick(() => {
    const root = codeContainer.value
    if (!root) return
    const target = root.querySelector(`[data-line="${f.line_start}"]`)
    if (target) target.scrollIntoView({ behavior: 'smooth', block: 'center' })
  })
}
</script>

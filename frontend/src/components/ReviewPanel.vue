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
    </header>

    <!-- I6: compact file navigation — single row with status filter
         chips and inline file chips. The big "Files changed" band
         from the previous design is gone; the file list is the
         actual review feed header. -->
    <div
      v-if="files.length"
      class="px-4 py-2 border-b border-gray-200 dark:border-gray-800 bg-gray-50/60 dark:bg-gray-950/40 flex flex-wrap items-center gap-2"
    >
      <span class="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
        {{ t('files.title') }}
      </span>
      <span class="text-xs text-gray-500 dark:text-gray-400">
        {{ t('files.summary', { total: files.length, added: statusCounts.added, modified: statusCounts.modified, deleted: statusCounts.deleted }) }}
      </span>
      <span class="flex-1"></span>
      <div class="flex items-center gap-1" role="tablist">
        <button
          v-for="f in statusFilters"
          :key="f.value"
          type="button"
          :class="[
            'px-2 py-0.5 rounded border text-[11px] transition',
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
    </div>

    <!-- The review feed. One <article> per file (filtered by
         fileStatusFilter). Each article has:
           1. a clickable header (path + status badge + counts +
              "expand / collapse" affordance)
           2. the diff with INLINE findings (one FindingCard right
              below each diff line that has a finding) -->
    <div class="divide-y divide-gray-100 dark:divide-gray-800">
      <div v-if="!findings.length && status !== 'completed'" class="p-6 text-center text-sm text-gray-500 dark:text-gray-400">
        <span v-if="status === 'idle'">{{ t('review.idle') }}</span>
        <span v-else-if="status === 'connecting'" class="inline-flex items-center gap-2">
          <span class="w-2 h-2 rounded-full bg-indigo-500 pulse-dot"></span>
          {{ t('review.connecting') }}
        </span>
        <span v-else>{{ t('review.waiting') }}</span>
      </div>

      <div v-else-if="!filteredFiles.length" class="p-6 text-center text-sm text-gray-500 dark:text-gray-400">
        <span v-if="filterSeverity || filterCategory">{{ t('review.noMatch') }}</span>
        <span v-else>{{ t('review.clean') }}</span>
      </div>

      <article
        v-for="f in filteredFiles"
        :key="f.path"
        :class="[
          'bg-white dark:bg-gray-900',
          activeFile === f.path ? 'ring-1 ring-inset ring-indigo-300 dark:ring-indigo-700' : '',
        ]"
      >
        <header
          :class="[
            'px-4 py-2 flex items-center gap-2 text-xs border-b cursor-pointer select-none',
            activeFile === f.path
              ? 'bg-indigo-50/60 dark:bg-indigo-900/20 border-indigo-200 dark:border-indigo-800/50'
              : 'bg-gray-50/60 dark:bg-gray-950/40 border-gray-100 dark:border-gray-800 hover:bg-gray-100/60',
          ]"
          @click="activeFile = activeFile === f.path ? null : f.path"
        >
          <span :class="fileStatusBadge(f.status).cls" :title="fileStatusLabel(f.status, locale.value)">
            {{ fileStatusBadge(f.status).icon }}
          </span>
          <span class="font-mono text-gray-800 dark:text-gray-200 truncate flex-1" :title="f.path">{{ f.path }}</span>
          <span v-if="(f.added_count || 0) || (f.removed_count || 0)" class="text-[10px] font-mono">
            <span class="text-emerald-600 dark:text-emerald-400">+{{ f.added_count || 0 }}</span>
            <span class="mx-0.5 text-gray-400">/</span>
            <span class="text-rose-600 dark:text-rose-400">-{{ f.removed_count || 0 }}</span>
          </span>
          <span
            v-if="findingsFor(f.path).length"
            class="text-[10px] text-gray-500 bg-gray-100 dark:bg-gray-800 rounded px-1.5"
          >
            {{ t('files.findingsFor', { n: findingsFor(f.path).length }) }}
          </span>
          <span class="text-[10px] text-gray-400 ml-1">
            {{ collapsedFiles.has(f.path) ? '▸' : '▾' }}
          </span>
        </header>
        <div v-show="!collapsedFiles.has(f.path)" class="p-2">
          <CodeView
            :diff="f.diff || []"
            :findings="findingsFor(f.path)"
            @locate="locate"
          />
        </div>
      </article>
    </div>

    <div class="px-4 py-2 border-t border-gray-100 dark:border-gray-800 flex items-center gap-3 text-[10px] text-gray-500 dark:text-gray-400">
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
</template>

<script setup>
import { ref, computed, watch } from 'vue'
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

const fileStatusFilter = ref('all')
const activeFile = ref(null)
const collapsedFiles = ref(new Set())

// Find findings for a given file path. Applies the severity /
// category filters so a file with no findings-after-filter is
// correctly treated as "no findings to render" (its article stays
// visible because the file itself is in the review, but no
// inline notes appear under its diff).
function findingsFor(path) {
  let list = props.findings.filter((f) => f.file_path === path)
  if (props.filterSeverity) list = list.filter((f) => f.severity === props.filterSeverity)
  if (props.filterCategory) list = list.filter((f) => f.category === props.filterCategory)
  return list
}

const visibleFindings = computed(() => {
  let list = props.findings
  if (props.filterSeverity) list = list.filter((f) => f.severity === props.filterSeverity)
  if (props.filterCategory) list = list.filter((f) => f.category === props.filterCategory)
  return list
})

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

const sortedFiles = computed(() => {
  const order = Object.fromEntries(FILE_STATUS_ORDER.map((s, i) => [s, i]))
  return [...props.files].sort((a, b) => {
    const da = order[a.status] ?? 99
    const db = order[b.status] ?? 99
    if (da !== db) return da - db
    return a.path.localeCompare(b.path)
  })
})

const filteredFiles = computed(() => {
  if (fileStatusFilter.value === 'all') return sortedFiles.value
  return sortedFiles.value.filter((f) => f.status === fileStatusFilter.value)
})

// As soon as a new review arrives, auto-expand the first changed
// file (the "interesting" one — not unchanged). This primes the
// review feed so the reader sees a useful default state on first
// load. We also auto-select it so `activeFile` is set for the
// jump-to-line scroll-into-view logic.
watch(
  () => props.files,
  (list) => {
    if (list.length && !activeFile.value) {
      const first = list.find((f) => f.status && f.status !== 'unchanged') || list[0]
      if (first) activeFile.value = first.path
    }
  },
  { immediate: true }
)
watch(
  () => props.findings,
  (list) => {
    if (list.length && !activeFile.value) {
      const firstFile = list[0]?.file_path
      if (firstFile) activeFile.value = firstFile
    }
  },
  { immediate: true }
)

function locate(f) {
  if (!f) return
  if (f.file_path) {
    activeFile.value = f.file_path
    // Auto-expand the target file in case the user had collapsed it.
    collapsedFiles.value.delete(f.file_path)
  }
  if (!f.line_start) return
  // The CodeView sets `data-line` on each rendered diff line; find
  // the next-tick DOM node for the file's diff and scroll the
  // matching line into view.
  setTimeout(() => {
    const articles = document.querySelectorAll('article')
    for (const a of articles) {
      if (a.textContent && a.textContent.includes(f.file_path)) {
        const line = a.querySelector(`[data-line="${f.line_start}"]`)
        if (line) {
          line.scrollIntoView({ behavior: 'smooth', block: 'center' })
          return
        }
      }
    }
  }, 50)
}
</script>

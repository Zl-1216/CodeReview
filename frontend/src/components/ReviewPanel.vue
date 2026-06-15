<template>
  <section id="findings-anchor" class="rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900">
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

    <!-- I7: sticky file tab bar + expand/collapse all.

         The user complaint was that with 15 findings spread across
         N files, the only way to navigate was to manually scroll
         through the whole vertical review feed — slow, no
         orientation, and the per-file collapse button was easy to
         miss. This row fixes both problems:

           1. A horizontal tab bar of one chip per file, sticky to
              the top of the panel so it stays in reach. Click a
              tab to smoothly scroll to that file's article. An
              IntersectionObserver marks the file currently in
              view as the active tab (ring + bolder colour).

           2. Two buttons, "Expand all" / "Collapse all", that
              walk the entire `collapsedFiles` Set in one pass.
              This is the "I want to see only one file's diff in
              detail" workflow: collapse everything, then click a
              tab to expand one.

         The status filter chips are kept on a second row so the
         user can scope the whole feed to "Added only" etc.
         without losing the file navigation. -->
    <div
      v-if="sortedFiles.length"
      class="sticky top-0 z-20 bg-white/95 dark:bg-gray-900/95 backdrop-blur border-b border-gray-200 dark:border-gray-800"
    >
      <div class="px-4 py-2 flex items-center gap-2 flex-wrap">
        <span class="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 shrink-0">
          {{ t('files.title') }}
        </span>
        <span class="text-xs text-gray-500 dark:text-gray-400 shrink-0">
          {{ t('files.summary', { total: sortedFiles.length, added: statusCounts.added, modified: statusCounts.modified, deleted: statusCounts.deleted }) }}
        </span>
        <span class="flex-1"></span>
        <button
          v-if="anyCollapsed"
          type="button"
          class="text-[11px] text-indigo-600 dark:text-indigo-400 hover:underline shrink-0"
          @click="expandAll"
        >
          {{ t('files.expandAll') }}
        </button>
        <button
          v-if="anyExpanded"
          type="button"
          class="text-[11px] text-gray-500 dark:text-gray-400 hover:underline shrink-0"
          @click="collapseAll"
        >
          {{ t('files.collapseAll') }}
        </button>
      </div>
      <div class="px-4 pb-2 -mx-1 overflow-x-auto code-scroll">
        <div class="flex items-center gap-1 min-w-max px-1">
          <button
            v-for="f in sortedFiles"
            :key="f.path"
            type="button"
            :data-file-tab="f.path"
            :class="[
              'flex items-center gap-1.5 rounded-md px-2 py-1 text-xs transition border shrink-0',
              activeFile === f.path
                ? 'border-indigo-400 bg-indigo-50 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-200 font-medium'
                : 'border-transparent text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 hover:border-gray-200 dark:hover:border-gray-700',
            ]"
            :title="f.path"
            @click="gotoFile(f.path)"
          >
            <span :class="fileStatusBadge(f.status).cls" :title="fileStatusLabel(f.status, locale.value)">
              {{ fileStatusBadge(f.status).icon }}
            </span>
            <span class="truncate max-w-[200px] font-mono">{{ f.path }}</span>
            <span
              v-if="findingsFor(f.path).length"
              class="text-[10px] bg-gray-200 dark:bg-gray-700 rounded-full px-1.5 shrink-0"
            >
              {{ findingsFor(f.path).length }}
            </span>
          </button>
        </div>
      </div>
      <div class="px-4 pb-2 flex items-center gap-1">
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

    <!-- The review feed. One <article> per file. Each article has
         a `data-file-path` so the scroll-spy can identify which
         file is currently in view and mark the matching tab as
         active. -->
    <div class="divide-y divide-gray-100 dark:divide-gray-800">
      <div v-if="!findings.length && status !== 'completed'" class="p-6 text-center text-sm text-gray-500 dark:text-gray-400">
        <span v-if="status === 'idle'">{{ t('review.idle') }}</span>
        <span v-else-if="status === 'connecting'" class="inline-flex items-center gap-2">
          <span class="w-2 h-2 rounded-full bg-indigo-500 pulse-dot"></span>
          {{ t('review.connecting') }}
        </span>
        <span v-else>{{ t('review.waiting') }}</span>
      </div>

      <div v-else-if="findings.length > 0 && !filteredFiles.length" class="p-6 text-center text-sm text-gray-500 dark:text-gray-400 space-y-1">
        <p>
          <span v-if="filterSeverity || filterCategory">{{ t('review.noMatch') }}</span>
          <span v-else-if="fileStatusFilter !== 'all'">{{ t('review.noFilesInStatus', { status: t('files.filter' + fileStatusFilter[0].toUpperCase() + fileStatusFilter.slice(1)) }) }}</span>
          <span v-else>{{ t('review.clean') }}</span>
        </p>
        <p class="text-xs text-gray-400 dark:text-gray-500">
          {{ t('review.clearFiltersHint') }}
        </p>
      </div>

      <div v-else-if="!findings.length && status === 'completed'" class="p-6 text-center text-sm text-gray-500 dark:text-gray-400">
        <p>{{ t('review.noFindingsInReview') }}</p>
        <p class="text-xs text-gray-400 dark:text-gray-500 mt-1">
          {{ t('review.reviewCompleteHint') }}
        </p>
      </div>

      <article
        v-for="f in filteredFiles"
        :key="f.path"
        :data-file-path="f.path"
        :class="[
          'bg-white dark:bg-gray-900 scroll-mt-32',
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
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
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

const anyCollapsed = computed(() => collapsedFiles.value.size > 0)
const anyExpanded = computed(() => {
  for (const f of filteredFiles.value) {
    if (!collapsedFiles.value.has(f.path)) return true
  }
  return false
})

function expandAll() {
  collapsedFiles.value = new Set()
}
function collapseAll() {
  collapsedFiles.value = new Set(filteredFiles.value.map((f) => f.path))
}

function gotoFile(path) {
  activeFile.value = path
  // Clear collapsed state for the target so the user actually
  // sees something when they jump to a file via the tab bar.
  collapsedFiles.value.delete(path)
  nextTick(() => {
    const el = document.querySelector(`article[data-file-path="${CSS.escape(path)}"]`)
    if (!el) return
    // The sticky tab bar is ~120px tall; offset by that much so
    // the file header doesn't sit flush under the bar.
    const rect = el.getBoundingClientRect()
    const targetY = (window.scrollY || 0) + rect.top - 128
    try { window.scrollTo({ top: targetY, behavior: 'smooth' }) }
    catch { window.scrollTo(0, targetY) }
  })
}

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

// Scroll-spy: IntersectionObserver that updates `activeFile` to
// whichever file's article is closest to the top of the viewport.
// Keeps the tab bar in sync with what the user is reading.
let _scrollObserver = null
function setupScrollSpy() {
  if (typeof IntersectionObserver === 'undefined') return
  _scrollObserver = new IntersectionObserver(
    (entries) => {
      // Pick the entry that's closest to the top of the viewport
      // (smallest non-negative boundingClientRect.top) so the tab
      // bar reflects the file the user is actually reading.
      const visible = entries
        .filter((e) => e.isIntersecting)
        .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
      if (visible.length && visible[0].target.dataset.filePath) {
        activeFile.value = visible[0].target.dataset.filePath
      }
    },
    {
      // Trigger when the article's top edge crosses the sticky
      // tab bar (~120px) and the bottom of the viewport. The
      // bottom margin (rootMargin) means: consider the article
      // "in view" when its top is between 120px from the top of
      // the viewport and 50% from the bottom.
      rootMargin: '-120px 0px -50% 0px',
      threshold: 0,
    }
  )
  // Observe every article's header. The articles are re-rendered
  // when files change; we re-attach the observer each time.
  for (const a of document.querySelectorAll('article[data-file-path]')) {
    _scrollObserver.observe(a)
  }
}

onMounted(() => {
  // Wait one tick so the articles are in the DOM.
  nextTick(setupScrollSpy)
})
onUnmounted(() => {
  _scrollObserver?.disconnect()
})

// Re-attach the observer when the file list changes (e.g. new
// findings arrive, or the user toggles the status filter). We
// watch the filtered list length rather than the array reference
// so a no-op update doesn't tear down the observer.
watch(
  () => filteredFiles.value.map((f) => f.path).join('|'),
  () => {
    _scrollObserver?.disconnect()
    nextTick(setupScrollSpy)
  }
)

function locate(f) {
  if (!f) return
  if (f.file_path) {
    activeFile.value = f.file_path
    collapsedFiles.value.delete(f.file_path)
  }
  if (!f.line_start) return
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

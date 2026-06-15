<template>
  <div class="min-h-screen bg-gray-50 dark:bg-gray-950 text-gray-900 dark:text-gray-100">
    <div class="max-w-[1280px] mx-auto px-4 py-6">
      <Header
        :history-total="history.total.value"
        :history-open="historyOpen"
        :current-review="review.currentReview.value"
        :tips-open="tipsOpen"
        @update:history-open="onHistoryToggle"
        @update:tips-open="onTipsToggle"
      />

      <div
        v-if="!review.currentReview.value"
        class="space-y-4"
      >
        <InputPanel @submit="review.submit" />
      </div>

      <div
        v-else
        id="findings-anchor"
        class="grid lg:grid-cols-[240px,1fr] gap-4 scroll-mt-4"
      >
        <!-- Left column: review header (title + actions + summary
             card + error banner) ABOVE the tree at narrow widths
             (single-column layout) and BELOW at desktop (header +
             summary span both columns; tree takes the left 240px
             column). The split here keeps the markup linear at
             every breakpoint. -->
        <div class="space-y-4 min-w-0 lg:col-start-2 lg:row-start-1">
          <div class="flex items-center justify-between gap-2 flex-wrap">
            <div>
              <h2 class="text-base font-semibold text-gray-900 dark:text-gray-100">
                {{ review.currentReview.value.title }}
              </h2>
              <p class="text-xs text-gray-500 dark:text-gray-400">
                {{ t('review.files', { n: review.currentReview.value.file_count, model: review.currentReview.value.model }) }}
              </p>
            </div>
            <div class="flex items-center gap-2">
              <button
                v-if="review.canCancel.value"
                type="button"
                class="rounded-md border border-gray-300 dark:border-gray-700 px-3 py-1.5 text-xs hover:border-red-400 hover:text-red-600"
                @click="review.cancel"
              >
                {{ t('review.cancel') }}
              </button>
              <button
                v-if="review.canRerun.value"
                type="button"
                class="rounded-md border border-gray-300 dark:border-gray-700 px-3 py-1.5 text-xs hover:border-indigo-400"
                @click="review.rerun"
              >
                {{ t('review.rerun') }}
              </button>
              <button
                type="button"
                class="rounded-md border border-gray-300 dark:border-gray-700 px-3 py-1.5 text-xs hover:border-indigo-400"
                @click="review.reset"
              >
                {{ t('review.new') }}
              </button>
            </div>
          </div>

          <SummaryCard
            :summary="session.summary.value"
            :status="session.status.value"
            :duration-ms="session.durationMs.value"
            :filter-severity="review.filterSeverity.value"
            :filter-category="review.filterCategory.value"
            :exportable="!!review.currentReview.value"
            @update:filter-severity="(v) => (review.filterSeverity.value = v)"
            @update:filter-category="(v) => (review.filterCategory.value = v)"
            @export="review.exportMarkdown"
          />

          <div
            v-if="session.error.value"
            class="rounded-md border border-red-200 dark:border-red-800/50 bg-red-50 dark:bg-red-900/20 p-3 text-sm text-red-700 dark:text-red-300"
          >
            {{ session.error.value }}
          </div>
        </div>

        <!-- Left column: file tree. Hidden when there are no files
             (e.g. a fresh streaming review before the first file
             event arrives). -->
        <aside
          v-if="review.files.value.length > 0"
          class="rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 overflow-hidden lg:col-start-1 lg:row-start-2 min-h-0"
        >
          <ReviewTreeHeader
            :status-filter="treeStatusFilter"
            :status-counts="statusCounts"
            :total-count="review.files.value.length"
            :visible-count="visibleFiles.length"
            @update:status-filter="treeStatusFilter = $event"
          />
          <ReviewTree
            :files="visibleFiles"
            :active-file="review.activeFile.value"
            :expanded="review.treeExpanded.value"
            :finding-counts="findingCounts"
            @select="onSelectFile"
            @toggle-folder="review.toggleFolder"
          />
        </aside>

        <!-- Right column: single-file viewer. -->
        <div class="min-w-0 lg:col-start-2 lg:row-start-2">
          <ReviewPanel
            :file="activeFileObj"
            :findings="activeFileFindings"
            :status="session.status.value"
            @locate="onLocate"
          />
        </div>
      </div>

      <!-- Right slide-in drawers. Both use the same component; the
           slot carries the content (history list vs. tips). Mutual
           exclusion: opening one closes the other. -->
      <HistoryDrawer
        :open="historyOpen"
        :aria-name="t('drawer.historyAria')"
        @update:open="onHistoryToggle"
      >
        <HistoryList
          :items="history.items.value"
          :total="history.total.value"
          :active-id="session.id.value"
          @open="review.open"
          @refresh="history.refresh"
          @remove="review.removeHistory"
        />
      </HistoryDrawer>

      <HistoryDrawer
        :open="tipsOpen"
        :aria-name="t('drawer.tipsAria')"
        @update:open="onTipsToggle"
      >
        <div class="rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4 text-xs text-gray-600 dark:text-gray-300 space-y-2">
          <div class="font-semibold text-gray-900 dark:text-gray-100">{{ t('app.tips.title') }}</div>
          <ul class="list-disc list-inside space-y-1 text-gray-500 dark:text-gray-400">
            <li>{{ t('app.tips.diff') }} <code class="font-mono text-[11px]">git diff</code>。</li>
            <li>{{ t('app.tips.click') }}</li>
            <li>{{ t('app.tips.filter') }}</li>
            <li>{{ t('app.tips.persist') }}</li>
          </ul>
        </div>
      </HistoryDrawer>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import Header from './components/Header.vue'
import InputPanel from './components/InputPanel.vue'
import ReviewPanel from './components/ReviewPanel.vue'
import SummaryCard from './components/SummaryCard.vue'
import ReviewTree from './components/ReviewTree.vue'
import ReviewTreeHeader from './components/ReviewTreeHeader.vue'
import HistoryList from './components/HistoryList.vue'
import HistoryDrawer from './components/HistoryDrawer.vue'
import { useReviewSession } from './composables/useReviewSession.js'
import { useReviewHistory } from './composables/useReviewHistory.js'
import { useReview } from './composables/useReview.js'
import { useI18n } from './i18n/messages.js'

const { t } = useI18n()
const session = useReviewSession()
const history = useReviewHistory()
history.refresh()
const review = useReview(session, history)

// Drawer state. Local to App.vue per the spec — these are
// transient UI toggles, not part of the review state. Mutual
// exclusion is enforced by the onHistoryToggle / onTipsToggle
// handlers: opening one closes the other.
const historyOpen = ref(false)
const tipsOpen = ref(false)

// Tree status filter chip (All / Added / Modified / Deleted). The
// ReviewTreeHeader emits update:statusFilter; we apply the filter
// here so both the header count and the visible file list see the
// same source of truth. Filter is NOT persisted — too transient
// to warrant the storage churn.
const treeStatusFilter = ref('all')

const statusCounts = computed(() => {
  const c = { added: 0, modified: 0, deleted: 0 }
  for (const f of review.files.value) {
    if (c[f.status] != null) c[f.status] += 1
  }
  return c
})

const visibleFiles = computed(() => {
  if (treeStatusFilter.value === 'all') return review.files.value
  return review.files.value.filter((f) => f.status === treeStatusFilter.value)
})

// Finding-count map: file_path → unfiltered count. Used by the
// tree to render badges that reflect "which file has findings
// worth checking" regardless of the active status filter (per
// spec).
const findingCounts = computed(() => {
  const m = {}
  for (const f of session.findings.value) {
    if (!f.file_path) continue
    m[f.file_path] = (m[f.file_path] || 0) + 1
  }
  return m
})

// Findings for the currently-active file. Filtering by
// severity / category is applied here (the viewer just renders).
const activeFileFindings = computed(() => {
  const path = review.activeFile.value
  if (!path) return []
  let list = session.findings.value.filter((f) => f.file_path === path)
  if (review.filterSeverity.value) {
    list = list.filter((f) => f.severity === review.filterSeverity.value)
  }
  if (review.filterCategory.value) {
    list = list.filter((f) => f.category === review.filterCategory.value)
  }
  return list
})

const activeFileObj = computed(() => {
  const path = review.activeFile.value
  if (!path) return null
  return review.files.value.find((f) => f.path === path) || null
})

function onSelectFile(path) {
  review.activeFile.value = path
}

function onLocate(f) {
  // The viewer re-emits `locate` for findings on a DIFFERENT file
  // (the inline `Jump to line` button on the current file's
  // findings just scrolls within the viewer's own scroll area;
  // CodeView's own handler does that part). Switch files when the
  // finding is on a different path.
  if (f && f.file_path && f.file_path !== review.activeFile.value) {
    review.activeFile.value = f.file_path
  }
}

function onHistoryToggle(next) {
  historyOpen.value = next
  if (next) tipsOpen.value = false
}

function onTipsToggle(next) {
  tipsOpen.value = next
  if (next) historyOpen.value = false
}
</script>

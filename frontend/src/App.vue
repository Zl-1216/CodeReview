<template>
  <div class="min-h-screen bg-gray-50 dark:bg-gray-950 text-gray-900 dark:text-gray-100">
    <div class="max-w-7xl mx-auto px-4 py-6">
      <Header />

      <div class="grid lg:grid-cols-[1fr,320px] gap-4">
        <div class="space-y-4 min-w-0">
          <InputPanel v-if="!review.currentReview.value" @submit="review.submit" />

          <template v-else>
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

            <div v-if="session.error.value" class="rounded-md border border-red-200 dark:border-red-800/50 bg-red-50 dark:bg-red-900/20 p-3 text-sm text-red-700 dark:text-red-300">
              {{ session.error.value }}
            </div>

            <ReviewPanel
              :findings="session.findings.value"
              :files="review.files.value"
              :status="session.status.value"
              :filter-severity="review.filterSeverity.value"
              :filter-category="review.filterCategory.value"
              @update:filter-severity="(v) => (review.filterSeverity.value = v)"
              @update:filter-category="(v) => (review.filterCategory.value = v)"
            />
          </template>
        </div>

        <aside class="space-y-4">
          <HistoryList
            :items="history.items.value"
            :total="history.total.value"
            :active-id="session.id.value"
            @open="review.open"
            @refresh="history.refresh"
            @remove="review.removeHistory"
          />

          <div class="rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4 text-xs text-gray-600 dark:text-gray-300 space-y-2">
            <div class="font-semibold text-gray-900 dark:text-gray-100">{{ t('app.tips.title') }}</div>
            <ul class="list-disc list-inside space-y-1 text-gray-500 dark:text-gray-400">
              <li>{{ t('app.tips.diff') }} <code class="font-mono text-[11px]">git diff</code>。</li>
              <li>{{ t('app.tips.click') }}</li>
              <li>{{ t('app.tips.filter') }}</li>
              <li>{{ t('app.tips.persist') }}</li>
            </ul>
          </div>
        </aside>
      </div>
    </div>
  </div>
</template>

<script setup>
import Header from './components/Header.vue'
import InputPanel from './components/InputPanel.vue'
import ReviewPanel from './components/ReviewPanel.vue'
import SummaryCard from './components/SummaryCard.vue'
import HistoryList from './components/HistoryList.vue'
import { useReviewSession } from './composables/useReviewSession.js'
import { useReviewHistory } from './composables/useReviewHistory.js'
import { useReview } from './composables/useReview.js'
import { useI18n } from './i18n/messages.js'

const { t } = useI18n()
const session = useReviewSession()
const history = useReviewHistory()
history.refresh()
const review = useReview(session, history)
</script>

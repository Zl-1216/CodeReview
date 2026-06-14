<template>
  <div v-if="!summary" class="rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4 space-y-3" aria-busy="true">
    <div class="flex items-center justify-between">
      <div class="h-4 w-32 bg-gray-100 dark:bg-gray-800 rounded animate-pulse"></div>
      <div class="h-3 w-20 bg-gray-100 dark:bg-gray-800 rounded animate-pulse"></div>
    </div>
    <div class="grid grid-cols-2 sm:grid-cols-5 gap-2">
      <div v-for="n in 5" :key="n" class="h-14 bg-gray-100 dark:bg-gray-800 rounded-md animate-pulse"></div>
    </div>
  </div>
  <div v-else class="rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4 space-y-3">
    <div class="flex items-center justify-between flex-wrap gap-2">
      <h3 class="text-sm font-semibold text-gray-900 dark:text-gray-100">{{ t('summary.title') }}</h3>
      <div class="flex items-center gap-3 text-xs text-gray-500">
        <span v-if="durationMs != null">{{ formattedDuration }}</span>
        <span class="inline-flex items-center gap-1.5">
          <span :class="['w-1.5 h-1.5 rounded-full', statusClass]"></span>
          {{ statusLabelText }}
        </span>
      </div>
    </div>

    <div class="grid grid-cols-2 sm:grid-cols-5 gap-2">
      <button
        v-for="sev in SEVERITY_ORDER"
        :key="sev"
        type="button"
        :class="[
          'rounded-md border px-2 py-2 text-center transition',
          filterSeverity === sev
            ? 'border-indigo-400 bg-indigo-50 dark:bg-indigo-900/30'
            : 'border-gray-200 dark:border-gray-800 hover:border-gray-300 dark:hover:border-gray-700',
        ]"
        @click="toggleSeverity(sev)"
      >
        <div class="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">{{ severityLabel(sev, locale.value) }}</div>
        <div class="text-lg font-semibold text-gray-900 dark:text-gray-100">
          {{ summary.by_severity?.[sev] || 0 }}
        </div>
      </button>
    </div>

    <div v-if="hasCategoryCounts" class="flex flex-wrap gap-1.5">
      <button
        v-for="cat in CATEGORY_ORDER"
        :key="cat"
        v-show="(summary.by_category?.[cat] || 0) > 0"
        type="button"
        :class="[
          'inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs border transition',
          filterCategory === cat
            ? 'border-indigo-400 bg-indigo-50 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-200'
            : 'border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:border-gray-300',
        ]"
        :title="t('summary.filterBy', { cat: categoryLabel(cat, locale.value) })"
        @click="toggleCategory(cat)"
      >
        <span>{{ CATEGORY_META[cat]?.icon }}</span>
        <span>{{ categoryLabel(cat, locale.value) }}</span>
        <span class="font-semibold text-gray-700 dark:text-gray-200">{{ summary.by_category?.[cat] || 0 }}</span>
      </button>
    </div>

    <p class="text-sm text-gray-700 dark:text-gray-300 leading-relaxed">
      {{ summary.overall_assessment }}
    </p>

    <!-- "View findings" CTA — the SummaryCard is the only thing
         visible in the first viewport, so the user needs an
         obvious affordance to discover the ReviewPanel below.
         Without this, the user sees the summary text and assumes
         that's all there is (a real complaint from production:
         "我没看到具体的代码信息和评审信息").

         We use <a href="#findings-anchor"> for the native
         fragment-navigation (most boring, most reliable scroll
         API in the browser), PLUS an @click handler that runs
         an imperative scroll + brief highlight animation as
         backup. Both code paths run on every click; whichever
         wins is fine. The user sees:
           1. The page scrolling to the ReviewPanel
           2. A 1.5-second yellow ring on the target so they
              can't miss it landed. -->
    <div class="flex items-center justify-between gap-2">
      <a
        v-if="summary.total_findings > 0"
        href="#findings-anchor"
        class="inline-flex items-center gap-1.5 rounded-md border border-indigo-300 dark:border-indigo-700 bg-indigo-50 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-200 hover:bg-indigo-100 dark:hover:bg-indigo-900/50 px-3 py-1.5 text-xs font-medium transition"
        @click="onViewFindingsClick"
      >
        <span>{{ t('summary.viewFindings', { n: summary.total_findings }) }}</span>
        <span aria-hidden="true">↓</span>
      </a>
      <button
        v-if="exportable"
        type="button"
        class="text-xs text-gray-500 hover:text-indigo-600 dark:hover:text-indigo-300"
        @click="$emit('export')"
      >
        {{ t('summary.download') }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { SEVERITY_ORDER, CATEGORY_META, CATEGORY_ORDER, formatDuration, severityLabel, categoryLabel } from '../utils/format.js'
import { useI18n } from '../i18n/messages.js'

const { t, locale } = useI18n()

const props = defineProps({
  summary: { type: Object, default: null },
  status: { type: String, default: 'idle' },
  durationMs: { type: Number, default: null },
  filterSeverity: { type: String, default: null },
  filterCategory: { type: String, default: null },
  exportable: { type: Boolean, default: false },
})

const emit = defineEmits(['update:filterSeverity', 'update:filterCategory', 'export'])

function toggleSeverity(sev) {
  emit('update:filterSeverity', props.filterSeverity === sev ? null : sev)
}
function toggleCategory(cat) {
  emit('update:filterCategory', props.filterCategory === cat ? null : cat)
}

// Belt-and-suspenders scroll handler. The <a href="#anchor">
// above already triggers native fragment navigation when the
// click event is allowed to propagate; we additionally call
// scrollIntoView + a brief outline ring on the target so the
// user definitively SEES the scroll happen (previous attempts
// silently no-op'd for the user, even when the anchor target
// existed in the DOM — most likely a browser extension,
// reduced-motion setting, or a sticky-header interaction
// suppressing the native fragment scroll).
function onViewFindingsClick() {
  if (typeof document === 'undefined') return
  const el = document.getElementById('findings-anchor')
  if (!el) {
    if (typeof console !== 'undefined') {
      console.warn('[SummaryCard] #findings-anchor not in DOM at click time')
    }
    return
  }
  // Imperative fallback: try the modern API, then a 2-arg form
  // for older browsers. We do NOT preventDefault — the <a href>
  // still does its native fragment scroll on top of this.
  try {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  } catch {
    const rect = el.getBoundingClientRect()
    const y = (window.scrollY || 0) + rect.top - 8
    try { window.scrollTo({ top: y, behavior: 'smooth' }) }
    catch { window.scrollTo(0, y) }
  }
  // Brief highlight so the user can't miss the target.
  el.classList.add('ring-4', 'ring-yellow-400', 'ring-offset-2', 'ring-offset-gray-50', 'dark:ring-offset-gray-950')
  setTimeout(() => {
    el.classList.remove('ring-4', 'ring-yellow-400', 'ring-offset-2', 'ring-offset-gray-50', 'dark:ring-offset-gray-950')
  }, 1500)
}

const statusLabelText = computed(() => {
  switch (props.status) {
    case 'idle': return t('summary.statusIdle')
    case 'connecting': return t('summary.statusConnecting')
    case 'streaming': return t('summary.statusStreaming')
    case 'completed': return t('summary.statusCompleted')
    case 'failed': return t('summary.statusFailed')
    default: return props.status
  }
})
const statusClass = computed(() => {
  switch (props.status) {
    case 'streaming': return 'bg-amber-500 pulse-dot'
    case 'completed': return 'bg-emerald-500'
    case 'failed': return 'bg-red-500'
    default: return 'bg-gray-400'
  }
})

const formattedDuration = computed(() => formatDuration(props.durationMs))

const hasCategoryCounts = computed(() => {
  const bc = props.summary?.by_category
  if (!bc) return false
  return Object.values(bc).some((n) => n > 0)
})
</script>

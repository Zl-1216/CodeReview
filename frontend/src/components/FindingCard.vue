<template>
  <article
    :class="[
      'rounded-lg border bg-white dark:bg-gray-900 transition-shadow',
      expanded ? 'shadow-md' : 'shadow-sm hover:shadow',
      severityBorder,
    ]"
  >
    <button
      type="button"
      class="w-full text-left px-4 py-3 flex items-start gap-3"
      :aria-expanded="expanded"
      @click="$emit('toggle', finding)"
    >
      <span class="mt-0.5 text-gray-400 transition-transform" :class="expanded ? 'rotate-90' : ''" aria-hidden="true">▸</span>
      <div class="flex-1 min-w-0">
        <div class="flex flex-wrap items-center gap-2">
          <SeverityBadge :severity="finding.severity" />
          <CategoryBadge :category="finding.category" />
          <span class="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
            {{ finding.title }}
          </span>
        </div>
        <div class="mt-1 text-xs text-gray-500 dark:text-gray-400 flex flex-wrap items-center gap-2">
          <span class="font-mono">{{ finding.file_path }}</span>
          <span v-if="finding.line_start">L{{ finding.line_start }}<span v-if="finding.line_end && finding.line_end !== finding.line_start">–{{ finding.line_end }}</span></span>
          <button
            v-if="finding.line_start"
            type="button"
            class="ml-auto underline text-indigo-600 dark:text-indigo-400 hover:no-underline"
            :aria-label="t('finding.jumpToAria')"
            @click.stop="$emit('locate', finding)"
          >
            {{ t('finding.jumpTo') }}
          </button>
        </div>
      </div>
    </button>

    <div v-if="expanded" class="px-4 pb-4 space-y-3 border-t border-gray-100 dark:border-gray-800 pt-3">
      <p class="text-sm text-gray-700 dark:text-gray-300 leading-relaxed whitespace-pre-line">
        {{ finding.detail }}
      </p>

      <div v-if="finding.code_snippet" class="relative rounded-md bg-gray-900 text-gray-100 px-3 py-2 overflow-x-auto">
        <button
          type="button"
          class="absolute top-1 right-1 text-[10px] uppercase tracking-wide text-gray-300 hover:text-white bg-gray-800/80 rounded px-1.5 py-0.5"
          :aria-label="t('finding.copyAria')"
          @click="copy(finding.code_snippet)"
        >
          {{ copyState === 'copied' ? t('finding.copied') : t('finding.copy') }}
        </button>
        <pre class="font-mono text-xs whitespace-pre"><code>{{ finding.code_snippet }}</code></pre>
      </div>

      <div v-if="finding.suggestion" class="rounded-md border border-emerald-200 dark:border-emerald-800/50 bg-emerald-50/40 dark:bg-emerald-900/10 px-3 py-2">
        <div class="text-xs font-medium text-emerald-700 dark:text-emerald-300 mb-1">{{ t('finding.suggestedFix') }}</div>
        <pre class="font-mono text-xs text-emerald-900 dark:text-emerald-100 whitespace-pre-wrap break-words"><code>{{ finding.suggestion }}</code></pre>
      </div>
    </div>
  </article>
</template>

<script setup>
import { computed, ref } from 'vue'
import SeverityBadge from './SeverityBadge.vue'
import CategoryBadge from './CategoryBadge.vue'
import { SEVERITY_META } from '../utils/format.js'
import { useI18n } from '../i18n/messages.js'

const { t } = useI18n()

const props = defineProps({
  finding: { type: Object, required: true },
  expanded: { type: Boolean, default: false },
})

defineEmits(['toggle', 'locate'])

const copyState = ref('idle')

async function copy(text) {
  if (!text) return
  try {
    if (navigator?.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
    } else {
      // Fallback for older browsers / non-secure contexts.
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

const severityBorder = computed(() => {
  const color = SEVERITY_META[props.finding.severity]?.color || 'gray'
  const palette = {
    red: 'border-red-300 dark:border-red-800/50',
    orange: 'border-orange-300 dark:border-orange-800/50',
    amber: 'border-amber-300 dark:border-amber-800/50',
    yellow: 'border-yellow-300 dark:border-yellow-800/50',
    sky: 'border-sky-300 dark:border-sky-800/50',
    gray: 'border-gray-200 dark:border-gray-800',
  }
  return palette[color] || palette.gray
})
</script>

<template>
  <div class="font-mono text-xs leading-relaxed overflow-auto code-scroll bg-gray-50 dark:bg-gray-950 rounded-md border border-gray-200 dark:border-gray-800">
    <div v-if="!lines.length" class="p-4 text-gray-400 italic">{{ t('codeView.empty') }}</div>
    <div v-else>
      <div
        v-for="row in lines"
        :key="row.n"
        :class="[
          'flex hover:bg-gray-100 dark:hover:bg-gray-900',
          row.highlight ? 'bg-amber-50 dark:bg-amber-900/20 border-l-2 border-amber-500' : '',
        ]"
        :data-line="row.n"
      >
        <div class="select-none text-right pr-3 pl-2 py-0.5 w-12 text-gray-400 border-r border-gray-200 dark:border-gray-800 bg-gray-50/50 dark:bg-gray-950/50 flex-shrink-0">
          {{ row.n }}
        </div>
        <pre class="px-3 py-0.5 whitespace-pre overflow-x-auto flex-1 text-gray-800 dark:text-gray-200">{{ row.text || ' ' }}</pre>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from '../i18n/messages.js'

const { t } = useI18n()

const props = defineProps({
  code: { type: String, default: '' },
  highlightLines: { type: Array, default: () => [] },
})

const lines = computed(() => {
  const highlight = new Set(props.highlightLines)
  return props.code.split('\n').map((text, i) => ({
    n: i + 1,
    text,
    highlight: highlight.has(i + 1),
  }))
})
</script>

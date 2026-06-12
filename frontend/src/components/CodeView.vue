<template>
  <div class="font-mono text-xs leading-relaxed overflow-auto code-scroll bg-gray-50 dark:bg-gray-950 rounded-md border border-gray-200 dark:border-gray-800">
    <div v-if="!rows.length" class="p-4 text-gray-400 italic">{{ t('codeView.empty') }}</div>
    <div v-else>
      <div
        v-for="row in rows"
        :key="row.id"
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
  // When `diff` is supplied, the component renders the per-line
  // change list with green / red / neutral backgrounds and + / − /
  // space markers, rather than a flat code listing. Falls back to
  // the flat listing when no diff is provided.
  diff: { type: Array, default: () => [] },
})

const highlight = computed(() => new Set(props.highlightLines))

const rows = computed(() => {
  if (props.diff && props.diff.length) {
    return props.diff.map((d, idx) => {
      // For added lines, anchor to the new line number. For removed
      // lines, anchor to the old line number. For context, the new
      // line. The `n` attribute is what `data-line` (and the
      // finding-jump scroll-into-view) keys on, so it should be
      // the line number visible in the gutter. The paired `oldN`
      // is shown in the smaller left column for diff context.
      const isAdd = d.type === 'added'
      const isRem = d.type === 'removed'
      const anchorN = isAdd || d.type === 'context' ? d.new_line : d.old_line
      return {
        id: `d${idx}`,
        n: anchorN,
        oldN: d.type === 'context' ? d.old_line : (isAdd ? '' : d.old_line),
        text: d.text,
        diffType: d.type,
        marker: isAdd ? '+' : isRem ? '−' : ' ',
        highlight: anchorN && highlight.value.has(anchorN),
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
  }))
})

function rowClass(row) {
  switch (row.diffType) {
    case 'added': return 'bg-emerald-50 dark:bg-emerald-900/15 hover:bg-emerald-100/80 dark:hover:bg-emerald-900/25'
    case 'removed': return 'bg-rose-50 dark:bg-rose-900/15 hover:bg-rose-100/80 dark:hover:bg-rose-900/25'
    default: return 'hover:bg-gray-100 dark:hover:bg-gray-900/60'
  }
}

function gutterClass(row) {
  switch (row.diffType) {
    case 'added': return 'text-emerald-600 dark:text-emerald-300 bg-emerald-100/40 dark:bg-emerald-900/20 border-emerald-200 dark:border-emerald-800/40'
    case 'removed': return 'text-rose-600 dark:text-rose-300 bg-rose-100/40 dark:bg-rose-900/20 border-rose-200 dark:border-rose-800/40'
    default: return 'text-gray-400 border-gray-200 dark:border-gray-800 bg-gray-50/50 dark:bg-gray-950/50'
  }
}

function markerClass(row) {
  switch (row.diffType) {
    case 'added': return 'text-emerald-600 dark:text-emerald-400'
    case 'removed': return 'text-rose-600 dark:text-rose-400'
    default: return 'text-gray-300 dark:text-gray-600'
  }
}

function textClass(row) {
  switch (row.diffType) {
    case 'added': return 'text-emerald-900 dark:text-emerald-100'
    case 'removed': return 'text-rose-900 dark:text-rose-100 line-through decoration-rose-400/50'
    default: return 'text-gray-800 dark:text-gray-200'
  }
}
</script>

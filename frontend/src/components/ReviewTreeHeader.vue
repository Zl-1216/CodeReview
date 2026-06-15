<template>
  <header class="px-3 py-2 border-b border-gray-200 dark:border-gray-800 space-y-1.5">
    <div class="flex items-center justify-between gap-2">
      <h3 class="text-xs font-semibold uppercase tracking-wide text-gray-700 dark:text-gray-300">
        {{ t('tree.title') }}
      </h3>
      <span class="text-[10px] text-gray-500 dark:text-gray-400 font-mono">
        {{ visibleCount }} / {{ totalCount }}
      </span>
    </div>
    <div class="flex items-center gap-1 flex-wrap">
      <button
        v-for="opt in statusOptions"
        :key="opt.value"
        type="button"
        :class="[
          'px-1.5 py-0.5 rounded border text-[10px] transition',
          statusFilter === opt.value
            ? 'border-indigo-400 bg-indigo-50 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-200'
            : 'border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:border-gray-300',
        ]"
        :title="opt.title || opt.label"
        @click="$emit('update:statusFilter', opt.value)"
      >
        <span v-if="opt.count != null" class="font-mono mr-0.5">{{ opt.count }}</span>
        {{ opt.label }}
      </button>
    </div>
  </header>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from '../i18n/messages.js'

const { t } = useI18n()

const props = defineProps({
  statusFilter: { type: String, required: true },
  // Map of status id → count (added/modified/deleted). The "all" chip
  // shows the total of the unfiltered file list.
  statusCounts: { type: Object, required: true },
  totalCount: { type: Number, required: true },
  visibleCount: { type: Number, required: true },
})
defineEmits(['update:statusFilter'])

const statusOptions = computed(() => [
  { value: 'all', label: t('files.filterAll'), count: null, title: '' },
  {
    value: 'added',
    label: t('files.filterAdded'),
    count: props.statusCounts.added || 0,
    title: '',
  },
  {
    value: 'modified',
    label: t('files.filterModified'),
    count: props.statusCounts.modified || 0,
    title: '',
  },
  {
    value: 'deleted',
    label: t('files.filterDeleted'),
    count: props.statusCounts.deleted || 0,
    title: '',
  },
])
</script>

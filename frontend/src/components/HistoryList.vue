<template>
  <section class="rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 overflow-hidden">
    <header class="px-4 py-3 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between">
      <div>
        <h2 class="text-sm font-semibold text-gray-900 dark:text-gray-100">{{ t('history.title') }}</h2>
        <p class="text-xs text-gray-500 dark:text-gray-400">{{ t('history.total', { n: total }) }}</p>
      </div>
      <button
        type="button"
        class="text-xs text-gray-500 hover:text-gray-900 dark:hover:text-gray-100"
        @click="$emit('refresh')"
      >
        {{ t('common.refresh') }}
      </button>
    </header>
    <div class="max-h-[40vh] overflow-y-auto code-scroll divide-y divide-gray-100 dark:divide-gray-800">
      <div v-if="!items.length" class="p-6 text-center text-sm text-gray-500 dark:text-gray-400">
        {{ t('history.empty') }}
      </div>
      <div
        v-for="r in items"
        :key="r.id"
        :class="[
          'group px-4 py-3 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800/50',
          activeId === r.id ? 'bg-indigo-50/50 dark:bg-indigo-900/20' : '',
        ]"
        @click="$emit('open', r.id)"
      >
        <div class="flex items-center justify-between gap-2">
          <div class="min-w-0 flex-1">
            <div class="text-sm font-medium text-gray-900 dark:text-gray-100 truncate flex items-center gap-1.5">
              <span class="truncate">{{ r.title }}</span>
              <span
                v-if="sourceBadge(r.source)"
                :class="['inline-block text-[10px] px-1.5 py-0.5 rounded font-mono shrink-0', sourceBadge(r.source).cls]"
                :title="sourceBadge(r.source).title"
              >
                {{ sourceBadge(r.source).label }}
              </span>
            </div>
            <div class="text-xs text-gray-500 dark:text-gray-400 mt-0.5 flex items-center gap-2 flex-wrap">
              <span class="font-mono">{{ t('history.fileCount', { n: r.file_count }) }}</span>
              <span>·</span>
              <span>{{ formatRelative(r.created_at, locale.value) }}</span>
              <span>·</span>
              <span class="font-mono">{{ r.model }}</span>
            </div>
          </div>
          <div class="flex flex-col items-end gap-1">
            <span :class="['text-xs px-1.5 py-0.5 rounded', statusClass(r.status)]">
              {{ statusLabel(r.status) }}
            </span>
            <span class="text-xs text-gray-500">
              <strong>{{ r.total_findings }}</strong> {{ t('history.findingCount', { n: r.total_findings }) }}
            </span>
          </div>
          <button
            type="button"
            class="ml-1 opacity-0 group-hover:opacity-100 focus:opacity-100 text-gray-400 hover:text-red-500 dark:hover:text-red-400 text-xs px-1 transition-opacity"
            :title="`Delete ${r.title}`"
            :aria-label="t('history.deleteAria', { title: r.title })"
            @click.stop="$emit('remove', r.id)"
          >
            ✕
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { formatRelative } from '../utils/format.js'
import { useI18n } from '../i18n/messages.js'

const { t, locale } = useI18n()

defineProps({
  items: { type: Array, default: () => [] },
  total: { type: Number, default: 0 },
  activeId: { type: String, default: null },
})
defineEmits(['open', 'refresh', 'remove'])

function statusClass(s) {
  switch (s) {
    case 'completed': return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300'
    case 'streaming': return 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300'
    case 'pending': return 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300'
    case 'failed': return 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300'
    default: return 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300'
  }
}

function statusLabel(s) {
  // The status string is server-owned ('completed', 'streaming', etc.);
  // the user-facing label is the same across both locales for now.
  return s
}

// Map a `source` value from the backend to a small badge shown next to
// the title. null / undefined = no badge (legacy rows). 'local' =
// REPO_PATH-backed. 'remote:<name>' = user-supplied remote repo.
function sourceBadge(source) {
  if (!source) return null
  if (source === 'local') {
    return {
      label: 'local',
      title: 'Reviewed from the configured local repo (REPO_PATH)',
      cls: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300',
    }
  }
  if (source.startsWith('remote:')) {
    const name = source.slice('remote:'.length)
    return {
      label: 'remote',
      title: `Reviewed from a user-supplied remote repo: ${name}`,
      cls: 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-300',
    }
  }
  return null
}
</script>

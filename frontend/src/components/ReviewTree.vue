<template>
  <nav
    class="text-sm select-none"
    :aria-label="t('tree.title')"
  >
    <ul v-if="rootNode.files.length || rootNode.folders.size" class="py-1">
      <li v-if="rootNode.files.length">
        <ul>
          <li
            v-for="f in rootNode.files"
            :key="`f-${f.path}`"
            class="px-2"
          >
            <button
              type="button"
              :class="[
                'group flex items-center gap-1.5 w-full text-left rounded px-2 py-1 text-xs transition',
                activeFile === f.path
                  ? 'bg-indigo-50 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-200 ring-1 ring-indigo-200 dark:ring-indigo-800'
                  : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800',
              ]"
              :data-file-path="f.path"
              :title="f.path"
              @click="$emit('select', f.path)"
            >
              <span :class="['shrink-0', statusBadge(f.status).cls]">
                {{ statusBadge(f.status).icon }}
              </span>
              <span class="font-mono truncate flex-1">{{ f.name || f.path }}</span>
              <span
                v-if="findingCounts[f.path]"
                class="text-[10px] bg-gray-200 dark:bg-gray-700 rounded-full px-1.5 shrink-0"
              >
                {{ findingCounts[f.path] }}
              </span>
            </button>
          </li>
        </ul>
      </li>
      <ReviewTreeFolder
        v-for="folder in folders"
        :key="`d-${folder.path}`"
        :folder="folder"
        :active-file="activeFile"
        :expanded="expanded"
        :finding-counts="findingCounts"
        :depth="1"
        @select="$emit('select', $event)"
        @toggle-folder="$emit('toggle-folder', $event)"
      />
    </ul>
    <div
      v-else
      class="p-4 text-center text-xs text-gray-500 dark:text-gray-400"
    >
      {{ t('tree.empty') }}
    </div>
  </nav>
</template>

<script setup>
import { computed } from 'vue'
import ReviewTreeFolder from './ReviewTreeFolder.vue'
import { useI18n } from '../i18n/messages.js'
import {
  groupFilesByFolder,
  fileStatusBadge,
  FILE_STATUS_META,
} from '../utils/format.js'

const { t } = useI18n()

const props = defineProps({
  files: { type: Array, required: true },
  activeFile: { type: String, default: null },
  expanded: { type: Set, required: true },
  // Map of file_path → number of findings. Counts are intentionally
  // unfiltered by status — finding badges should reflect "which file
  // has findings worth checking" regardless of the active filter.
  findingCounts: { type: Object, default: () => ({}) },
})
defineEmits(['select', 'toggle-folder'])

// We pre-compute the tree off the input files (filtered at the
// App.vue level). Folder pruning for status filters happens here by
// simply using the already-filtered list — if a folder ends up with
// zero visible files, the parent renders no children for it.
const rootNode = computed(() => groupFilesByFolder(props.files))
const folders = computed(() => Array.from(rootNode.value.folders.values()))

// Re-export so the template can keep using `statusBadge(...)` — the
// helper lives in format.js so it can be unit-tested there.
function statusBadge(status) {
  return fileStatusBadge(status)
}
// `FILE_STATUS_META` is referenced here so a future import of the
// visual metadata can be re-exported from this file without a
// separate import block.
void FILE_STATUS_META
</script>

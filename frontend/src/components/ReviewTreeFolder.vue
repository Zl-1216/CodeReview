<template>
  <div>
    <button
      type="button"
      :class="[
        'flex items-center gap-1 w-full text-left rounded px-2 py-1 text-xs transition',
        'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800',
      ]"
      :style="{ paddingLeft: `${depth * 8 + 4}px` }"
      :aria-expanded="isOpen ? 'true' : 'false'"
      :aria-label="isOpen ? t('tree.collapseAria', { folder: folder.name }) : t('tree.expandAria', { folder: folder.name })"
      @click="$emit('toggle-folder', folder.path)"
    >
      <span class="text-[10px] text-gray-400 dark:text-gray-500 inline-block w-3 shrink-0 text-center">
        {{ isOpen ? '▾' : '▸' }}
      </span>
      <span class="font-mono truncate flex-1">{{ folder.name }}</span>
      <span
        v-if="folderFindingCount > 0"
        class="text-[10px] bg-gray-200 dark:bg-gray-700 rounded-full px-1.5 shrink-0"
      >
        {{ folderFindingCount }}
      </span>
    </button>
    <ul v-show="isOpen">
      <li
        v-for="f in folder.files"
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
          :style="{ paddingLeft: `${(depth + 1) * 8 + 4}px` }"
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
      <ReviewTreeFolder
        v-for="child in childFolders"
        :key="`d-${child.path}`"
        :folder="child"
        :active-file="activeFile"
        :expanded="expanded"
        :finding-counts="findingCounts"
        :depth="depth + 1"
        @select="$emit('select', $event)"
        @toggle-folder="$emit('toggle-folder', $event)"
      />
    </ul>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from '../i18n/messages.js'
import { fileStatusBadge } from '../utils/format.js'

const { t } = useI18n()

const props = defineProps({
  folder: { type: Object, required: true },
  activeFile: { type: String, default: null },
  expanded: { type: Set, required: true },
  findingCounts: { type: Object, default: () => ({}) },
  depth: { type: Number, default: 1 },
})
defineEmits(['select', 'toggle-folder'])

const isOpen = computed(() => props.expanded.has(props.folder.path))
const childFolders = computed(() => Array.from(props.folder.folders.values()))

// Sum of finding badges under this folder, including all descendants
// — gives the user a hint that "this folder has N findings" before
// expanding it.
const folderFindingCount = computed(() => {
  let n = 0
  function visit(node) {
    for (const f of node.files) {
      n += props.findingCounts[f.path] || 0
    }
    for (const c of node.folders.values()) visit(c)
  }
  visit(props.folder)
  return n
})

function statusBadge(status) {
  return fileStatusBadge(status)
}
</script>

<template>
  <section class="rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 min-h-[60vh]">
    <!-- The viewer is intentionally header-light. The file-tree
         already shows the path + status + counts; duplicating them
         here would just be visual noise. The only thing the viewer
         adds is the +N/-M line counts, which the tree doesn't show. -->
    <header
      v-if="file"
      class="px-4 py-2 border-b border-gray-200 dark:border-gray-800 flex items-center gap-2 text-xs"
    >
      <span :class="fileStatusBadge(file.status).cls" :title="fileStatusLabel(file.status, locale.value)">
        {{ fileStatusBadge(file.status).icon }}
      </span>
      <span class="font-mono text-gray-800 dark:text-gray-200 truncate flex-1" :title="file.path">
        {{ file.path }}
      </span>
      <span
        v-if="(file.added_count || 0) || (file.removed_count || 0)"
        class="text-[10px] font-mono shrink-0"
      >
        <span class="text-emerald-600 dark:text-emerald-400">{{ t('viewer.added', { n: file.added_count || 0 }) }}</span>
        <span class="mx-0.5 text-gray-400">/</span>
        <span class="text-rose-600 dark:text-rose-400">{{ t('viewer.removed', { n: file.removed_count || 0 }) }}</span>
      </span>
    </header>

    <!-- Hard-replace: no fade transition. The viewer flips files
         instantly; an animation would read as loading latency. The
         scrollTop reset is done in the watcher below. -->
    <div
      ref="bodyEl"
      class="p-2 overflow-y-auto code-scroll"
      style="max-height: calc(100vh - 220px);"
    >
      <div v-if="!file" class="p-6 text-center text-sm text-gray-500 dark:text-gray-400">
        {{ t('viewer.chooseFile') }}
      </div>

      <div v-else-if="file && !(file.diff && file.diff.length)" class="p-6 text-center text-sm text-gray-500 dark:text-gray-400">
        {{ t('viewer.noDiff') }}
      </div>

      <CodeView
        v-else
        :diff="file.diff || []"
        :findings="findings"
        @locate="locate"
      />
      <!-- Closing p-2 / div tags belong to the body's parent (max-h
           scroll container). CodeView is the only child. -->
    </div>
  </section>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import CodeView from './CodeView.vue'
import { useI18n } from '../i18n/messages.js'
import { fileStatusBadge, fileStatusLabel } from '../utils/format.js'

const { t, locale } = useI18n()

const props = defineProps({
  // Single file object. `null` means "no file selected" (e.g. the
  // review has no files yet, or the user has just opened a fresh
  // review and the tree hasn't chosen a default yet).
  file: { type: Object, default: null },
  // Findings for THIS file. Filtering by severity / category is
  // the parent's job — the viewer just renders what it's given.
  findings: { type: Array, default: () => [] },
  // Status string for the empty-state messaging in the parent (kept
  // here so the per-file body can show a "no findings" hint when
  // the review is still streaming and the first finding hasn't
  // arrived yet). Currently unused inside the body — the file
  // picker in App.vue already shows the global state.
  status: { type: String, default: 'idle' },
})

const bodyEl = ref(null)

// On every `file` change, reset the viewer's scroll position to 0
// so the user lands at the top of the new file's diff. Without
// this, switching from a long file to a short one would leave the
// scroll position pointing past the end of the new content.
watch(
  () => props.file?.path,
  () => {
    nextTick(() => {
      if (bodyEl.value) bodyEl.value.scrollTop = 0
    })
  }
)

// `locate` is forwarded from the CodeView's @locate emit so the
// parent (App.vue) can change the active file. The viewer itself
// doesn't know about useReview; it just emits the finding and
// lets the parent switch files.
const emit = defineEmits(['locate'])
function locate(f) {
  if (!f || !f.file_path) return
  emit('locate', f)
}
</script>

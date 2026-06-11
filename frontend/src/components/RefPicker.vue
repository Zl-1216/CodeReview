<template>
  <div class="relative">
    <label class="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">{{ label }}</label>
    <div class="flex items-stretch">
      <input
        v-model="model"
        type="text"
        :placeholder="placeholder"
        class="flex-1 rounded-l-md border border-r-0 border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-950 px-3 py-2 text-sm font-mono focus:border-indigo-500 focus:outline-none"
      />
      <button
        type="button"
        class="rounded-r-md border border-gray-300 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 px-2 text-gray-500 hover:text-indigo-600 hover:border-indigo-400"
        :title="open ? t('refPicker.closePicker') : t('refPicker.openPicker')"
        :aria-label="open ? t('refPicker.closePickerAria', { label }) : t('refPicker.openPickerAria', { label })"
        @click="toggleOpen"
      >
        <span :class="['inline-block transition-transform', open ? 'rotate-180' : '']">▾</span>
      </button>
    </div>
    <div
      v-if="open"
      class="absolute z-20 left-0 right-0 mt-1 max-h-72 overflow-y-auto code-scroll rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shadow-lg text-sm"
    >
      <div class="p-2 text-xs text-gray-500 dark:text-gray-400 flex items-center justify-between border-b border-gray-100 dark:border-gray-800">
        <span>{{ t('refPicker.branches') }}</span>
        <button class="hover:text-indigo-600" @click="$emit('refresh')">{{ t('common.refresh') }}</button>
      </div>
      <div v-if="!branches.length" class="p-3 text-xs text-gray-400 italic">{{ t('refPicker.noBranches') }}</div>
      <button
        v-for="b in branches"
        :key="'b-' + b.name"
        type="button"
        class="w-full text-left px-3 py-1.5 hover:bg-gray-50 dark:hover:bg-gray-800/50 flex items-center justify-between gap-2"
        @click="pick(b.name)"
      >
        <span class="font-mono text-gray-900 dark:text-gray-100">{{ b.name }}</span>
        <span class="text-[10px] font-mono text-gray-400">{{ b.sha }}</span>
      </button>
      <div v-if="tags.length" class="p-2 text-xs text-gray-500 dark:text-gray-400 border-t border-gray-100 dark:border-gray-800">{{ t('refPicker.tags') }}</div>
      <button
        v-for="tag in tags"
        :key="'t-' + tag.name"
        type="button"
        class="w-full text-left px-3 py-1.5 hover:bg-gray-50 dark:hover:bg-gray-800/50 flex items-center justify-between gap-2"
        @click="pick(tag.name)"
      >
        <span class="font-mono text-gray-700 dark:text-gray-200">{{ tag.name }}</span>
        <span class="text-[10px] font-mono text-gray-400">{{ tag.sha }}</span>
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useI18n } from '../i18n/messages.js'

const { t } = useI18n()

const props = defineProps({
  modelValue: { type: String, default: '' },
  label: { type: String, default: '' },
  placeholder: { type: String, default: '' },
  branches: { type: Array, default: () => [] },
  tags: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'refresh'])

const open = ref(false)
// Two-way binding via a computed getter/setter. Previously this was
// a local ref initialised from props.modelValue and never synced, so
// any external update (reset, default-branch assignment on git status
// load) would leave the input showing stale text. With the computed,
// the displayed value always reflects the canonical prop.
const model = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

function pick(name) {
  emit('update:modelValue', name)
  open.value = false
}

function toggleOpen() {
  open.value = !open.value
  // Refresh on first open (empty list) — branches don't change every
  // time the user clicks the caret, so a repeated open shouldn't
  // refetch the same list.
  if (open.value && props.branches.length === 0 && props.tags.length === 0) {
    emit('refresh')
  }
}

function onDocClick(e) {
  if (!e.target.closest('.relative')) open.value = false
}

onMounted(() => document.addEventListener('click', onDocClick))
onUnmounted(() => document.removeEventListener('click', onDocClick))
</script>

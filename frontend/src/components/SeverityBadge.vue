<template>
  <span :class="['inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium', classes]">
    <span :class="['w-1.5 h-1.5 rounded-full', dotClasses]"></span>
    {{ label }}
  </span>
</template>

<script setup>
import { computed } from 'vue'
import { SEVERITY_META, severityLabel } from '../utils/format.js'
import { useI18n } from '../i18n/messages.js'

const props = defineProps({
  severity: { type: String, required: true },
})

const { locale } = useI18n()

const meta = computed(() => SEVERITY_META[props.severity] || { color: 'gray', weight: 0 })
const label = computed(() => severityLabel(props.severity, locale.value))

const palette = {
  red: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300',
  orange: 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300',
  amber: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',
  yellow: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-300',
  sky: 'bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-300',
  gray: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300',
}
const classes = computed(() => palette[meta.value.color] || palette.gray)

const dotPalette = {
  red: 'bg-red-500',
  orange: 'bg-orange-500',
  amber: 'bg-amber-500',
  yellow: 'bg-yellow-500',
  sky: 'bg-sky-500',
  gray: 'bg-gray-500',
}
const dotClasses = computed(() => dotPalette[meta.value.color] || dotPalette.gray)
</script>

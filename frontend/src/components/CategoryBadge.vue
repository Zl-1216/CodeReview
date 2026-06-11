<template>
  <span class="inline-flex items-center gap-1 text-xs text-gray-600 dark:text-gray-300">
    <span aria-hidden="true">{{ icon }}</span>
    <span>{{ label }}</span>
  </span>
</template>

<script setup>
import { computed } from 'vue'
import { CATEGORY_META, categoryLabel } from '../utils/format.js'
import { useI18n } from '../i18n/messages.js'

const props = defineProps({
  category: { type: String, required: true },
})

const { locale } = useI18n()

const meta = computed(() => CATEGORY_META[props.category] || { icon: '•' })
const label = computed(() => categoryLabel(props.category, locale.value))
const icon = computed(() => meta.value.icon)
</script>

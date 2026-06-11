<template>
  <header class="mb-6 flex items-center justify-between flex-wrap gap-3">
    <div class="flex items-center gap-3">
      <div class="w-9 h-9 rounded-lg bg-indigo-600 text-white flex items-center justify-center font-bold text-base">
        CR
      </div>
      <div>
        <h1 class="text-lg font-semibold text-gray-900 dark:text-gray-100">{{ t('app.title') }}</h1>
        <p class="text-xs text-gray-500 dark:text-gray-400">
          {{ t('app.tagline') }}
        </p>
      </div>
    </div>
    <div class="flex items-center gap-3 text-xs text-gray-500">
      <span class="inline-flex items-center gap-1.5">
        <span :class="['w-1.5 h-1.5 rounded-full', aiEnabled ? 'bg-emerald-500' : 'bg-amber-500']"></span>
        <span>{{ aiEnabled ? t('header.aiProvider', { model: provider }) : t('header.aiMock') }}</span>
      </span>
      <div class="inline-flex items-center rounded-md bg-gray-100 dark:bg-gray-800 p-0.5 text-[11px]">
        <button
          v-for="loc in SUPPORTED_LOCALES"
          :key="loc"
          type="button"
          :class="[
            'px-2 py-0.5 rounded transition',
            locale.value === loc
              ? 'bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 shadow-sm'
              : 'text-gray-500 hover:text-gray-900 dark:hover:text-gray-100',
          ]"
          :aria-label="t('header.lang') + ': ' + loc"
          @click="setLocale(loc)"
        >
          {{ localeLabel(loc) }}
        </button>
      </div>
    </div>
  </header>
</template>

<script setup>
import { computed } from 'vue'
import { useConfig } from '../composables/useConfig.js'
import { useI18n, setLocale, SUPPORTED_LOCALES } from '../i18n/messages.js'

const { t, locale } = useI18n()
const { config } = useConfig()

const aiEnabled = computed(() => config.value?.ai_enabled ?? false)
const provider = computed(() => config.value?.default_model ?? 'unknown')

function localeLabel(loc) {
  return loc === 'zh' ? '中' : 'EN'
}
</script>

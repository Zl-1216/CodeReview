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
      <!-- I7: header buttons for the two drawers. History is hidden
           when there is no history to show (no review has ever
           completed). Tips is hidden during a review so it doesn't
           distract the user from the active workflow. The two
           buttons are mutually exclusive — clicking one closes the
           other (enforced in App.vue). -->
      <button
        v-if="historyTotal > 0"
        type="button"
        :class="[
          'rounded-md border px-2 py-1 transition',
          historyOpen
            ? 'border-indigo-400 bg-indigo-50 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-200'
            : 'border-gray-300 dark:border-gray-700 hover:border-indigo-400',
        ]"
        :aria-pressed="historyOpen ? 'true' : 'false'"
        :aria-label="t('drawer.historyAria')"
        @click="$emit('update:historyOpen', !historyOpen)"
      >
        📜 {{ t('header.historyButton') }} ({{ historyTotal }})
      </button>
      <button
        v-if="!currentReview"
        type="button"
        :class="[
          'rounded-md border px-2 py-1 transition',
          tipsOpen
            ? 'border-indigo-400 bg-indigo-50 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-200'
            : 'border-gray-300 dark:border-gray-700 hover:border-indigo-400',
        ]"
        :aria-pressed="tipsOpen ? 'true' : 'false'"
        :aria-label="t('drawer.tipsAria')"
        @click="$emit('update:tipsOpen', !tipsOpen)"
      >
        ⋯ {{ t('header.tipsButton') }}
      </button>
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

defineProps({
  // Number of historical reviews. The History button is hidden when
  // this is 0 — there is nothing to show. Wired by App.vue from
  // `history.total`.
  historyTotal: { type: Number, default: 0 },
  historyOpen: { type: Boolean, default: false },
  // True when a review is currently active. The Tips button is
  // hidden while a review is running so the user isn't pulled out
  // of their workflow by a decorative button.
  currentReview: { type: [Object, null], default: null },
  tipsOpen: { type: Boolean, default: false },
})
defineEmits(['update:historyOpen', 'update:tipsOpen'])

function localeLabel(loc) {
  return loc === 'zh' ? '中' : 'EN'
}
</script>

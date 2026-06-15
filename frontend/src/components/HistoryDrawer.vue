<template>
  <Teleport to="body">
    <transition
      enter-active-class="transition-opacity duration-200"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition-opacity duration-200"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div
        v-if="open"
        class="fixed inset-0 z-40 bg-transparent"
        :aria-label="ariaName"
        @click="onBackdrop"
      ></div>
    </transition>
    <transition
      enter-active-class="transition-transform duration-200 ease-out"
      enter-from-class="translate-x-full"
      enter-to-class="translate-x-0"
      leave-active-class="transition-transform duration-200 ease-in"
      leave-from-class="translate-x-0"
      leave-to-class="translate-x-full"
    >
      <aside
        v-if="open"
        ref="panelEl"
        :class="[
          'fixed top-0 right-0 z-50 h-full w-[400px] max-w-[100vw] bg-white dark:bg-gray-900 border-l border-gray-200 dark:border-gray-800 shadow-xl overflow-y-auto code-scroll',
        ]"
        role="dialog"
        :aria-modal="true"
        :aria-label="ariaName"
        tabindex="-1"
        @keydown.esc.stop="$emit('update:open', false)"
      >
        <header class="sticky top-0 z-10 flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-800 bg-white/95 dark:bg-gray-900/95 backdrop-blur">
          <h2 class="text-sm font-semibold text-gray-900 dark:text-gray-100">
            <slot name="title">{{ t('history.title') }}</slot>
          </h2>
          <button
            ref="closeBtnEl"
            type="button"
            class="text-gray-500 hover:text-gray-900 dark:hover:text-gray-100 text-sm px-2 py-1 rounded"
            :aria-label="t('drawer.closeAria')"
            @click="$emit('update:open', false)"
          >
            ✕
          </button>
        </header>
        <div class="p-2">
          <slot />
        </div>
      </aside>
    </transition>
  </Teleport>
</template>

<script setup>
import { ref, computed, watch, nextTick, onBeforeUnmount } from 'vue'
import { useI18n } from '../i18n/messages.js'

const { t } = useI18n()

const props = defineProps({
  open: { type: Boolean, default: false },
  // Localized a11y label for the drawer. Defaults to "History drawer"
  // but the tips drawer overrides it.
  ariaName: { type: String, default: '' },
})
const emit = defineEmits(['update:open'])

const panelEl = ref(null)
const closeBtnEl = ref(null)

// Default ariaName to the History drawer label if the caller didn't
// pass one.
const ariaName = computed(() => props.ariaName || t('drawer.historyAria'))

// Focus management: on open, move focus to the close button so the
// user can dismiss with Enter/Space without having to tab through
// the whole drawer first.
watch(
  () => props.open,
  async (isOpen) => {
    if (isOpen) {
      await nextTick()
      closeBtnEl.value?.focus()
    } else if (panelEl.value) {
      panelEl.value.blur()
    }
  }
)

// Global Esc key listener. The drawer's own keydown handler covers
// the case where focus is inside the panel; this one covers the case
// where focus has drifted out (e.g. user clicked into the viewer
// behind the backdrop). Mutual-exclusion logic in App.vue decides
// which drawer closes first when both are stacked.
function onKeydown(e) {
  if (e.key === 'Escape' && props.open) {
    e.stopPropagation()
    emit('update:open', false)
  }
}

if (typeof document !== 'undefined') {
  document.addEventListener('keydown', onKeydown)
}
onBeforeUnmount(() => {
  if (typeof document !== 'undefined') {
    document.removeEventListener('keydown', onKeydown)
  }
})

// Spec: "click outside drawer on viewer" closes the drawer. The
// backdrop is transparent (no overlay dim) but covers the full
// viewport; the drawer panel sits on top of it. Clicking on the
// visible part of the viewer (which is actually the backdrop from
// the event's perspective) triggers this handler.
function onBackdrop() {
  emit('update:open', false)
}
</script>

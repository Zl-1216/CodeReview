<template>
  <section class="rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4 space-y-4">
    <header class="flex items-center justify-between flex-wrap gap-2">
      <div>
        <h2 class="text-sm font-semibold text-gray-900 dark:text-gray-100">{{ t('input.title') }}</h2>
        <p class="text-xs text-gray-500 dark:text-gray-400">
          {{ t('input.hintRemote') }}
        </p>
      </div>
    </header>

    <div class="space-y-3">
      <div v-if="config?.requires_api_key && !hasApiKey" class="rounded-md border border-amber-200 dark:border-amber-800/50 bg-amber-50 dark:bg-amber-900/20 p-2 text-xs text-amber-700 dark:text-amber-300 space-y-1.5">
        <div>{{ t('input.apiKeyRequired') }}</div>
        <details class="text-amber-700/80 dark:text-amber-300/80">
          <summary class="cursor-pointer select-none hover:text-amber-900 dark:hover:text-amber-100">
            {{ t('input.apiKeyWhereToFind') }}
          </summary>
        </details>
        <div v-if="apiKeyLastError" class="text-red-600 dark:text-red-400">
          {{ apiKeyLastError }}
        </div>
        <div v-if="!apiKeyStorageOk" class="text-red-600 dark:text-red-400">
          {{ t('input.apiKeyPersistFailed') }}
        </div>
        <div class="flex items-center gap-1.5">
          <input
            v-model="apiKeyInput"
            :type="showApiKey ? 'text' : 'password'"
            :placeholder="t('input.apiKeyPlaceholder')"
            autocomplete="off"
            class="flex-1 rounded-md border border-amber-300 dark:border-amber-700 bg-white dark:bg-gray-950 px-2 py-1 text-xs font-mono focus:border-amber-500 focus:outline-none"
            @keyup.enter="saveApiKey"
          />
          <button
            type="button"
            class="rounded-md border border-amber-300 dark:border-amber-700 text-amber-700 dark:text-amber-300 px-2 py-1 text-xs hover:bg-amber-100 dark:hover:bg-amber-900/30"
            :title="showApiKey ? t('input.apiKeyHide') : t('input.apiKeyShow')"
            @click="showApiKey = !showApiKey"
          >
            {{ showApiKey ? t('input.apiKeyHide') : t('input.apiKeyShow') }}
          </button>
          <button
            type="button"
            class="rounded-md bg-amber-600 hover:bg-amber-700 text-white px-2 py-1 text-xs font-medium"
            @click="saveApiKey"
          >
            {{ t('input.apiKeySave') }}
          </button>
        </div>
      </div>
      <div v-else-if="config?.requires_api_key && hasApiKey" class="flex items-center justify-between gap-2 text-xs text-emerald-700 dark:text-emerald-300 rounded-md border border-emerald-200 dark:border-emerald-800/50 bg-emerald-50 dark:bg-emerald-900/20 px-2 py-1">
        <span>{{ t('input.apiKeySet') }}</span>
        <button type="button" class="text-emerald-700 dark:text-emerald-300 hover:text-red-600 dark:hover:text-red-400" @click="clearStoredApiKey">
          {{ t('input.apiKeyClear') }}
        </button>
      </div>
      <div v-if="!remoteStatus" class="space-y-2">
        <input
          v-model="remoteUrl"
          type="text"
          :placeholder="t('input.remoteUrlPlaceholder')"
          class="w-full rounded-md border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-950 px-3 py-2 text-sm font-mono focus:border-indigo-500 focus:outline-none"
        />
        <input
          v-model="remoteToken"
          type="password"
          :placeholder="t('input.remoteTokenPlaceholder')"
          autocomplete="off"
          class="w-full rounded-md border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-950 px-3 py-2 text-sm font-mono focus:border-indigo-500 focus:outline-none"
        />
        <div v-if="remoteError" class="rounded-md border border-red-200 dark:border-red-800/50 bg-red-50 dark:bg-red-900/20 p-2 text-xs text-red-700 dark:text-red-300 space-y-1">
          <div>{{ remoteError }}</div>
          <div v-if="isRemoteTimeoutError">{{ t('input.remoteTimeoutHint') }}</div>
          <div v-else-if="isNetworkError">{{ t('input.remoteNetworkErrorHint') }}</div>
        </div>
        <button
          type="button"
          :disabled="!canConnect || connecting"
          class="inline-flex items-center gap-1.5 rounded-md bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-400 text-white px-3 py-1.5 text-xs font-medium transition"
          @click="connectRemote"
        >
          <span v-if="connecting" class="inline-block w-3 h-3 rounded-full bg-white/70 pulse-dot"></span>
          <span>{{ connecting ? t('input.connecting') : t('input.connect') }}</span>
        </button>
      </div>

      <div v-else class="space-y-3">
        <div class="rounded-md border border-gray-200 dark:border-gray-800 bg-gray-50/50 dark:bg-gray-950/50 px-3 py-2 text-xs text-gray-600 dark:text-gray-300 flex items-center justify-between gap-2 flex-wrap">
          <div>
            <span class="text-gray-500">{{ t('input.remoteConnected', { name: remoteStatus.name }) }}</span>
            <span v-if="remoteStatus.head" class="ml-2 font-mono">{{ remoteStatus.head }}</span>
            <span v-if="remoteStatus.head_sha" class="text-gray-400 ml-1">({{ remoteStatus.head_sha }})</span>
          </div>
          <div class="flex items-center gap-2">
            <button type="button" class="text-gray-500 hover:text-indigo-600" :disabled="connecting" @click="refreshRemote">
              {{ connecting ? t('input.connecting') : t('input.refresh') }}
            </button>
            <button type="button" class="text-gray-500 hover:text-red-600" @click="disconnectRemote">
              {{ t('input.disconnect') }}
            </button>
          </div>
        </div>

        <div v-if="!remoteBranches.length" class="text-xs text-gray-400 italic">
          {{ t('input.remoteNoBranches') }}
        </div>

        <div v-else class="grid sm:grid-cols-2 gap-2">
          <RefPicker
            v-model="gitBase"
            :label="t('input.baseRef')"
            :placeholder="t('input.baseRefPlaceholder')"
            :branches="remoteBranches"
            :tags="remoteTags"
            :loading="loadingRefs"
            @refresh="loadRemoteRefs"
          />
          <RefPicker
            v-model="gitHead"
            :label="t('input.headRef')"
            :placeholder="t('input.headRefPlaceholder')"
            :branches="remoteBranches"
            :tags="remoteTags"
            :loading="loadingRefs"
            @refresh="loadRemoteRefs"
          />
        </div>

        <div>
          <input
            v-model="gitPath"
            type="text"
            :placeholder="t('input.pathFilterPlaceholder')"
            class="w-full rounded-md border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-950 px-3 py-2 text-sm font-mono focus:border-indigo-500 focus:outline-none"
          />
        </div>

        <div class="flex items-center justify-between gap-2">
          <button
            type="button"
            :disabled="!canPreview || previewing"
            class="rounded-md border border-gray-300 dark:border-gray-700 px-3 py-1.5 text-xs hover:border-indigo-400 disabled:opacity-50"
            @click="previewDiff"
          >
            <span v-if="previewing">{{ t('common.loading') }}</span>
            <span v-else>{{ t('input.previewDiff') }}</span>
          </button>
          <div v-if="previewSummary" class="text-xs text-gray-500 dark:text-gray-400 text-right">
            {{ t('input.previewSummary', { n: previewSummary.file_count, bin: previewSummary.binary }) }}
            <details v-if="previewSummary.stat" class="mt-1">
              <summary class="cursor-pointer text-gray-400 hover:text-gray-600">{{ t('input.showStat') }}</summary>
              <pre class="mt-1 text-[10px] font-mono text-gray-500 whitespace-pre">{{ previewSummary.stat }}</pre>
            </details>
          </div>
        </div>

        <div v-if="previewError" class="rounded-md border border-red-200 dark:border-red-800/50 bg-red-50 dark:bg-red-900/20 p-2 text-xs text-red-700 dark:text-red-300">
          {{ previewError }}
        </div>
      </div>
    </div>

    <div class="space-y-2">
      <div class="text-xs font-medium text-gray-700 dark:text-gray-300">{{ t('input.focuses') }}</div>
      <div class="flex flex-wrap gap-2">
        <label
          v-for="f in focusOptions"
          :key="f"
          :class="[
            'inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs cursor-pointer border transition',
            focuses.includes(f)
              ? 'border-indigo-400 bg-indigo-50 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-200'
              : 'border-gray-300 dark:border-gray-700 text-gray-600 dark:text-gray-300 hover:border-gray-400',
          ]"
        >
          <input type="checkbox" :value="f" v-model="focuses" class="hidden" />
          {{ categoryLabel(f, locale.value) }}
        </label>
      </div>
    </div>

    <div class="flex items-center justify-end gap-2 pt-2 border-t border-gray-100 dark:border-gray-800">
      <span v-if="error" class="text-xs text-red-500">{{ error }}</span>
      <button
        type="button"
        :disabled="!canSubmit || busy"
        class="inline-flex items-center gap-1.5 rounded-md bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-400 text-white px-4 py-2 text-sm font-medium transition"
        @click="onSubmit"
      >
        <span v-if="busy" class="inline-block w-3 h-3 rounded-full bg-white/70 pulse-dot"></span>
        <span>{{ busy ? t('input.submitting') : t('input.run') }}</span>
      </button>
    </div>
  </section>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, defineAsyncComponent } from 'vue'
import { api, getApiKey, setApiKey, clearApiKey } from '../utils/api.js'
import { useConfig } from '../composables/useConfig.js'
import { useI18n } from '../i18n/messages.js'
import { categoryLabel } from '../utils/format.js'
// Lazy-load the ref picker — it's only needed once a remote is
// connected, so the dropdown's keyboard handling and click-outside
// logic stay out of the initial bundle.
const RefPicker = defineAsyncComponent(() => import('./RefPicker.vue'))

const props = defineProps({
  defaultFocuses: { type: Array, default: () => ['bug', 'security', 'performance', 'style'] },
})
const emit = defineEmits(['submit'])

const { config } = useConfig()
const { t, locale } = useI18n()

// --- Remote mode state ---------------------------------------------------
// The user pastes a URL (+ optional token), we hit the
// /api/git/remote/* endpoints, and reuse the RefPicker + diff
// pipeline. `remoteStatus` is null until the user successfully
// connects; on disconnect we drop it and clear the refs.
const remoteUrl = ref('')
const remoteToken = ref('')
const remoteId = ref(null)
const remoteStatus = ref(null)
const remoteBranches = ref([])
const remoteTags = ref([])
const connecting = ref(false)
const remoteError = ref(null)
// HTTP status of the last /api/git/remote/clone (or related) failure.
// Kept in lockstep with `remoteError` so the error-class computeds
// below can branch on the actual response status (502 = network,
// 504 = timeout) rather than re-parse the human-readable message —
// the message may legitimately contain "timed out" AND a gnutls
// marker when a subprocess timeout reclassified a network failure,
// which would otherwise fall into both buckets.
const remoteErrorStatus = ref(null)

const gitBase = ref('')
const gitHead = ref('')
const gitPath = ref('')
const loadingRefs = ref(false)
const previewing = ref(false)
const previewSummary = ref(null)
const previewFiles = ref([])
const previewError = ref(null)

const focuses = ref([...props.defaultFocuses])
const focusOptions = ['bug', 'security', 'performance', 'style', 'best_practice', 'documentation']
const busy = ref(false)
const error = ref(null)

// --- API key (Review/Upload/Remote writes) ------------------------------
// When the server is configured with REVIEW_API_KEY, every write needs
// a Bearer token. The key is stored in localStorage by utils/api.js
// (getApiKey/setApiKey/clearApiKey); here we just expose a reactive
// flag so the UI can switch between the "enter key" banner and the
// "key set ✓" indicator. The actual auth header is injected by
// `request()` in api.js on every call.
//
// Reactivity is bridged via the `codereview:apikey-changed` event that
// api.js fires on every mutation (including the 401 auto-clear). The
// previous design only re-read storage on config changes, which left
// a window where the auto-clear had cleared localStorage but the UI
// still showed a green "API key saved ✓" indicator — and the next
// request would fire with no Authorization header and 401 again,
// which is a baffling loop.
const apiKeyInput = ref('')
const hasApiKey = ref(false)
const showApiKey = ref(false)
const apiKeyStorageOk = ref(true)
const apiKeyLastError = ref('')
function saveApiKey() {
  if (!apiKeyInput.value) return
  const result = setApiKey(apiKeyInput.value)
  apiKeyStorageOk.value = result.storageOk
  hasApiKey.value = !!result.value
  apiKeyInput.value = ''
  apiKeyLastError.value = ''
}
function clearStoredApiKey() {
  clearApiKey()
  hasApiKey.value = false
  apiKeyInput.value = ''
  apiKeyLastError.value = ''
}
function refreshHasApiKey() {
  hasApiKey.value = !!getApiKey()
}
function onApiKeyChanged() {
  refreshHasApiKey()
  // The event doesn't carry the value (would have to dispatch through
  // a CustomEvent detail; we don't bother since storage IS the source
  // of truth). On a clear, also surface the last error so the user
  // sees why their key disappeared.
  if (!hasApiKey.value) {
    apiKeyLastError.value = t('input.apiKeyWasInvalid')
  }
}
refreshHasApiKey()
onMounted(() => window.addEventListener('codereview:apikey-changed', onApiKeyChanged))
onUnmounted(() => window.removeEventListener('codereview:apikey-changed', onApiKeyChanged))

// Fallback: also refresh on config load (covers edge cases where the
// event was missed, e.g. when this component mounts after the key
// was already set by a sibling).
watch(() => config.value, refreshHasApiKey)

async function previewDiff() {
  if (!remoteId.value) return
  previewing.value = true
  previewError.value = null
  previewSummary.value = null
  try {
    const r = await api.gitRemoteDiff(remoteId.value, {
      base: gitBase.value,
      head: gitHead.value,
      path: gitPath.value,
    })
    previewFiles.value = r.files
    previewSummary.value = {
      file_count: r.files.length,
      binary: r.binary_skipped,
      stat: r.stat,
    }
  } catch (e) {
    previewError.value = e.message
    previewFiles.value = []
  } finally {
    previewing.value = false
  }
}

watch(focuses, (val) => {
  if (val.length === 0) focuses.value = ['bug']
})

const canPreview = computed(() => gitBase.value.trim() && gitHead.value.trim())
const canConnect = computed(() => remoteUrl.value.trim().length > 5)
// True when the last /api/git/remote/clone failure is a backend
// timeout (HTTP 504 → RemoteGitTimeoutError). Distinct from
// `isNetworkError` so the user gets a different hint: a 504 means
// the clone ran for the full REMOTE_GIT_CLONE_TIMEOUT without
// finishing — the repo is large or the connection is slow — whereas
// a 502 means git gave up because it couldn't reach the host. Both
// are caused by the backend's environment, not by the user's input,
// but the remediation is different (raise the timeout vs fix the
// proxy / switch to SSH).
const isRemoteTimeoutError = computed(() => remoteErrorStatus.value === 504)
// True when the failure is a network / TLS / proxy problem (HTTP 502
// → RemoteGitNetworkError). The status code is the source of truth
// — the regex fallback is for the rare case where `.status` was
// dropped by an older wrapper, so we still surface a useful hint
// instead of nothing.
const isNetworkError = computed(() => {
  if (remoteErrorStatus.value === 502) return true
  if (remoteErrorStatus.value === 504) return false
  if (typeof remoteError.value !== 'string') return false
  return /Network error|gnutls|non-properly terminated|connection (refused|reset|timed out)|proxy/i.test(
    remoteError.value,
  )
})
const canSubmit = computed(() => {
  if (!remoteId.value) return false
  if (previewFiles.value.length > 0) return true
  return canPreview.value
})

async function onSubmit() {
  busy.value = true
  error.value = null
  try {
    if (!remoteId.value) {
      error.value = 'Connect to a remote repo first'
      return
    }
    if (previewFiles.value.length === 0) await previewDiff()
    const files = previewFiles.value
    if (!files.length) {
      error.value = 'No files to review'
      return
    }
    const name = remoteStatus.value?.name || remoteUrl.value
    const title = `${name}@${gitBase.value}..${gitHead.value}`
    const source = `remote:${name}`
    emit('submit', { files, focuses: focuses.value, title, source })
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}

// --- Remote-mode actions ------------------------------------------------
function _setRemoteFromStatus(s) {
  remoteStatus.value = s
  remoteBranches.value = s.branches || []
  remoteTags.value = s.tags || []
  // Pick sensible defaults: base = default_branch, head = HEAD or
  // first available branch. Only overwrite if the user hasn't
  // already typed something into the picker.
  if (s.default_branch && !gitBase.value) {
    gitBase.value = s.default_branch
  }
  if (s.head && !gitHead.value) {
    gitHead.value = s.head
  }
}

async function connectRemote() {
  if (!canConnect.value) return
  connecting.value = true
  remoteError.value = null
  remoteErrorStatus.value = null
  try {
    const s = await api.gitRemoteClone({ url: remoteUrl.value, token: remoteToken.value })
    remoteId.value = s.id
    _setRemoteFromStatus(s)
  } catch (e) {
    remoteError.value = e.message
    remoteErrorStatus.value = e.status ?? null
  } finally {
    connecting.value = false
  }
}

async function refreshRemote() {
  if (!remoteId.value) return
  connecting.value = true
  remoteError.value = null
  remoteErrorStatus.value = null
  try {
    const s = await api.gitRemoteClone({ url: remoteUrl.value, token: remoteToken.value, refresh: true })
    _setRemoteFromStatus(s)
  } catch (e) {
    remoteError.value = e.message
    remoteErrorStatus.value = e.status ?? null
  } finally {
    connecting.value = false
  }
}

async function loadRemoteRefs() {
  if (!remoteId.value) return
  loadingRefs.value = true
  try {
    const s = await api.gitRemoteStatus(remoteId.value)
    _setRemoteFromStatus(s)
  } catch {
    // ignore — the picker can still show what we have
  } finally {
    loadingRefs.value = false
  }
}

async function disconnectRemote() {
  if (remoteId.value) {
    try { await api.gitRemoteDelete(remoteId.value) } catch { /* best effort */ }
  }
  remoteId.value = null
  remoteStatus.value = null
  remoteBranches.value = []
  remoteTags.value = []
  remoteError.value = null
  remoteErrorStatus.value = null
  // Drop any preview we computed against the old remote
  previewFiles.value = []
  previewSummary.value = null
  previewError.value = null
}
</script>

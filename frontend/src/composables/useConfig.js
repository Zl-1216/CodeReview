import { ref, onMounted } from 'vue'
import { api } from '../utils/api.js'

// Fetches the public config (AI enabled, default model, focuses) once on
// mount. Exposed as a singleton so every component sees the same value.
// Call `refresh()` to re-fetch (e.g. after a backend restart, or to recover
// from a previous load error).

const config = ref(null)
const loading = ref(false)
const error = ref(null)
let inFlight = null

export function useConfig() {
  onMounted(() => {
    if (config.value == null && !inFlight) refresh()
  })
  return { config, loading, error, refresh }
}

export async function refresh() {
  if (inFlight) return inFlight
  loading.value = true
  error.value = null
  inFlight = (async () => {
    try {
      config.value = await api.config()
    } catch (e) {
      error.value = e.message
    } finally {
      loading.value = false
      inFlight = null
    }
  })()
  return inFlight
}

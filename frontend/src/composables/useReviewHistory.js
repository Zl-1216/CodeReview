import { ref } from 'vue'
import { api } from '../utils/api.js'

// History list of past reviews. Holds the page state and a refresh() method.

export function useReviewHistory() {
  const items = ref([])
  const total = ref(0)
  const loading = ref(false)
  const error = ref(null)
  const limit = 50
  const offset = ref(0)

  async function refresh() {
    loading.value = true
    error.value = null
    try {
      const data = await api.listReviews(limit, offset.value)
      items.value = data.items
      total.value = data.total
    } catch (e) {
      error.value = e.message
    } finally {
      loading.value = false
    }
  }

  async function remove(id) {
    try {
      await api.deleteReview(id)
      await refresh()
    } catch (e) {
      error.value = e.message
    }
  }

  return { items, total, loading, error, limit, offset, refresh, remove }
}

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { getApiKey, setApiKey, clearApiKey } from './api.js'

describe('api.js — API key storage', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('getApiKey returns "" when nothing is stored', () => {
    expect(getApiKey()).toBe('')
  })

  it('setApiKey stores the key; getApiKey reads it back', () => {
    setApiKey('secret-1')
    expect(getApiKey()).toBe('secret-1')
  })

  it('setApiKey("") removes the key', () => {
    setApiKey('secret-1')
    setApiKey('')
    expect(getApiKey()).toBe('')
  })

  it('clearApiKey removes the key', () => {
    setApiKey('secret-1')
    clearApiKey()
    expect(getApiKey()).toBe('')
  })

  it('setApiKey / clearApiKey handle a non-string input gracefully', () => {
    // We don't assert against the actual storage; we just verify the
    // call doesn't throw when the storage layer is in an unusual state.
    // (Private-mode localStorage isn't reliably mockable across
    // vitest's environment backends, so the try/except path in
    // setApiKey is best-effort and untested at the unit level here.)
    expect(() => setApiKey(null)).not.toThrow()
    expect(() => setApiKey(undefined)).not.toThrow()
    expect(() => clearApiKey()).not.toThrow()
  })
})

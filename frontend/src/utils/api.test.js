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

  it('setApiKey trims whitespace before persisting', () => {
    // A copy-paste of a key from a config file often leaves a trailing
    // newline or leading whitespace. The backend's hmac.compare_digest
    // is strict, so we strip before writing.
    setApiKey('  secret-1  \n')
    expect(getApiKey()).toBe('secret-1')
  })

  it('setApiKey returns a result object exposing value + storageOk', () => {
    const r = setApiKey('abc')
    expect(r.value).toBe('abc')
    expect(r.storageOk).toBe(true)
  })

  it('setApiKey dispatches codereview:apikey-changed on every mutation', () => {
    const handler = vi.fn()
    window.addEventListener('codereview:apikey-changed', handler)
    setApiKey('a')
    expect(handler).toHaveBeenCalledTimes(1)
    setApiKey('b')
    expect(handler).toHaveBeenCalledTimes(2)
    clearApiKey()
    expect(handler).toHaveBeenCalledTimes(3)
    window.removeEventListener('codereview:apikey-changed', handler)
  })

  it('setApiKey / clearApiKey handle a non-string input gracefully', () => {
    expect(() => setApiKey(null)).not.toThrow()
    expect(() => setApiKey(undefined)).not.toThrow()
    expect(() => clearApiKey()).not.toThrow()
  })
})

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { getApiKey, setApiKey, clearApiKey, api } from './api.js'

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

describe('api.js — request() error contract', () => {
  // The remote-git flow needs to distinguish a 504 (clone timeout —
  // the user should be told "the repo is large / connection is slow,
  // ask the operator to raise REMOTE_GIT_CLONE_TIMEOUT") from a 502
  // (network / proxy / TLS — the user should be told "fix the proxy
  // or switch to SSH"). The backend already returns the right status
  // for each branch of _classify_and_raise, so the client just needs
  // the status to survive onto the thrown Error. This used to be
  // dropped — only the .message string was kept — and the UI had to
  // regex the message to tell the cases apart, which was both fragile
  // and easy to false-match (the timeout wrapper contains the substring
  // 'timed out', which the network regex also matched, hiding the
  // real cause).
  it('attaches the HTTP status to the thrown Error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(
          JSON.stringify({ detail: 'git command timed out after 300s' }),
          { status: 504, statusText: 'Gateway Timeout' },
        ),
      ),
    )
    try {
      await api.health()
      expect.fail('expected request to throw')
    } catch (e) {
      expect(e).toBeInstanceOf(Error)
      expect(e.message).toContain('timed out')
      expect(e.status).toBe(504)
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('attaches a non-2xx status (e.g. 502) the same way', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            detail:
              "fatal: ... GnuTLS recv error (-110) ... — Network error reaching the remote.",
          }),
          { status: 502, statusText: 'Bad Gateway' },
        ),
      ),
    )
    try {
      await api.health()
      expect.fail('expected request to throw')
    } catch (e) {
      expect(e.status).toBe(502)
      expect(e.message).toContain('Network error')
    } finally {
      vi.unstubAllGlobals()
    }
  })
})

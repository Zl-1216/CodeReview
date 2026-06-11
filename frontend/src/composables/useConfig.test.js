import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock the api module before importing the composable so the singleton
// in useConfig picks up the mocked fetch.
vi.mock('../utils/api.js', () => ({
  api: {
    config: vi.fn(),
  },
}))

import { useConfig as _useConfig } from './useConfig.js'

describe('useConfig', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Reset the module-level singleton between tests by importing fresh.
    vi.resetModules()
  })

  it('refresh() resolves with config and exposes it via useConfig', async () => {
    const payload = { ai_enabled: true, default_model: 'x', focuses: ['bug'] }
    const apiMod = await import('../utils/api.js')
    apiMod.api.config.mockResolvedValue(payload)
    const cfgMod = await import('./useConfig.js')

    await cfgMod.refresh()
    const { config, loading, error } = cfgMod.useConfig()
    expect(config.value).toEqual(payload)
    expect(loading.value).toBe(false)
    expect(error.value).toBeNull()
  })

  it('refresh() sets error.value on failure and clears loading', async () => {
    const apiMod = await import('../utils/api.js')
    apiMod.api.config.mockRejectedValue(new Error('boom'))
    const cfgMod = await import('./useConfig.js')

    await cfgMod.refresh()
    const { config, loading, error } = cfgMod.useConfig()
    expect(config.value).toBeNull()
    expect(loading.value).toBe(false)
    expect(error.value).toBe('boom')
  })

  it('concurrent refresh() calls share a single in-flight request', async () => {
    const apiMod = await import('../utils/api.js')
    let calls = 0
    apiMod.api.config.mockImplementation(async () => {
      calls++
      await new Promise((r) => setTimeout(r, 10))
      return { ai_enabled: false }
    })
    const cfgMod = await import('./useConfig.js')

    const [a, b] = await Promise.all([cfgMod.refresh(), cfgMod.refresh()])
    expect(a).toBe(b) // same promise
    expect(calls).toBe(1)
  })
})

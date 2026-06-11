import { describe, it, expect } from 'vitest'
import {
  severityRank,
  formatDateTime,
  formatRelative,
  formatBytes,
  formatDuration,
  severityLabel,
  categoryLabel,
  SEVERITY_ORDER,
  CATEGORY_ORDER,
} from './format.js'

describe('severityRank', () => {
  it('orders severities high→low', () => {
    expect(severityRank('critical')).toBeGreaterThan(severityRank('high'))
    expect(severityRank('high')).toBeGreaterThan(severityRank('medium'))
    expect(severityRank('medium')).toBeGreaterThan(severityRank('low'))
    expect(severityRank('low')).toBeGreaterThan(severityRank('info'))
  })

  it('returns -1 for unknown severities', () => {
    expect(severityRank('bogus')).toBe(-1)
  })
})

describe('formatDateTime', () => {
  it('formats an ISO timestamp into YYYY-MM-DD HH:MM', () => {
    const out = formatDateTime('2026-06-06T14:09:08.123456')
    expect(out).toBe('2026-06-06 14:09')
  })

  it('returns the input as-is when not a date', () => {
    expect(formatDateTime('not a date')).toBe('not a date')
  })

  it('returns empty string for null/undefined', () => {
    expect(formatDateTime(null)).toBe('')
    expect(formatDateTime(undefined)).toBe('')
  })
})

describe('formatRelative', () => {
  it('returns seconds for sub-minute (en)', () => {
    const tenSecAgo = new Date(Date.now() - 10_000).toISOString()
    expect(formatRelative(tenSecAgo, 'en')).toBe('10s ago')
  })

  it('returns minutes for sub-hour (en)', () => {
    const fiveMinAgo = new Date(Date.now() - 5 * 60_000).toISOString()
    expect(formatRelative(fiveMinAgo, 'en')).toBe('5m ago')
  })

  it('returns hours for sub-day (en)', () => {
    const threeHrAgo = new Date(Date.now() - 3 * 3_600_000).toISOString()
    expect(formatRelative(threeHrAgo, 'en')).toBe('3h ago')
  })

  it('returns days for >= 1 day (en)', () => {
    const twoDaysAgo = new Date(Date.now() - 2 * 86_400_000).toISOString()
    expect(formatRelative(twoDaysAgo, 'en')).toBe('2d ago')
  })

  it('returns Chinese formatting (秒前 / 分钟前 / 小时前 / 天前)', () => {
    expect(formatRelative(new Date(Date.now() - 10_000).toISOString(), 'zh')).toBe('10 秒前')
    expect(formatRelative(new Date(Date.now() - 5 * 60_000).toISOString(), 'zh')).toBe('5 分钟前')
    expect(formatRelative(new Date(Date.now() - 3 * 3_600_000).toISOString(), 'zh')).toBe('3 小时前')
    expect(formatRelative(new Date(Date.now() - 2 * 86_400_000).toISOString(), 'zh')).toBe('2 天前')
  })
})

describe('severityLabel / categoryLabel (i18n)', () => {
  it('returns the English label for the en locale', () => {
    expect(severityLabel('critical', 'en')).toBe('Critical')
    expect(severityLabel('high', 'en')).toBe('High')
    expect(categoryLabel('bug', 'en')).toBe('Bug')
    expect(categoryLabel('best_practice', 'en')).toBe('Best practice')
  })

  it('returns the Chinese label for the zh locale', () => {
    expect(severityLabel('critical', 'zh')).toBe('严重')
    expect(severityLabel('high', 'zh')).toBe('高')
    expect(categoryLabel('bug', 'zh')).toBe('缺陷')
    expect(categoryLabel('best_practice', 'zh')).toBe('最佳实践')
  })

  it('falls back to en when the key is unknown in either locale', () => {
    expect(severityLabel('bogus', 'en')).toBe('bogus')
    expect(severityLabel('bogus', 'zh')).toBe('bogus')
  })
})

describe('formatBytes', () => {
  it('formats < 1KB as B', () => {
    expect(formatBytes(0)).toBe('0 B')
    expect(formatBytes(512)).toBe('512 B')
  })
  it('formats < 1MB as KB', () => {
    expect(formatBytes(1024)).toBe('1.0 KB')
    expect(formatBytes(1536)).toBe('1.5 KB')
  })
  it('formats >= 1MB as MB', () => {
    expect(formatBytes(1024 * 1024)).toBe('1.00 MB')
  })
})

describe('formatDuration', () => {
  it('shows ms under one second', () => {
    expect(formatDuration(42)).toBe('42ms')
    expect(formatDuration(999)).toBe('999ms')
  })
  it('shows seconds at >= 1000ms', () => {
    expect(formatDuration(1000)).toBe('1.0s')
    expect(formatDuration(12_345)).toBe('12.3s')
  })
  it('returns empty string for null', () => {
    expect(formatDuration(null)).toBe('')
  })
})

describe('order constants', () => {
  it('severity order is critical first, info last', () => {
    expect(SEVERITY_ORDER[0]).toBe('critical')
    expect(SEVERITY_ORDER.at(-1)).toBe('info')
  })
  it('category order starts with bug and security', () => {
    expect(CATEGORY_ORDER.slice(0, 2)).toEqual(['bug', 'security'])
  })
})

import { describe, it, expect } from 'vitest'
import {
  severityRank,
  fileStatusBadge,
  fileStatusLabel,
  formatDateTime,
  formatRelative,
  formatBytes,
  formatDuration,
  severityLabel,
  categoryLabel,
  groupFilesByFolder,
  listFolderPaths,
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


// --- File status badge (I5) -----------------------------------------

describe('format.js — file status badge', () => {
  it('returns a class + icon for every known status', () => {
    for (const s of ['added', 'modified', 'deleted', 'renamed', 'unchanged']) {
      const b = fileStatusBadge(s)
      expect(b.icon).toBeTruthy()
      expect(b.cls).toContain('inline-flex')
    }
  })

  it('falls back to the unchanged style for unknown / missing status', () => {
    const unknown = fileStatusBadge('mystery')
    const missing = fileStatusBadge(undefined)
    const ref = fileStatusBadge('unchanged')
    expect(unknown.cls).toBe(ref.cls)
    expect(missing.cls).toBe(ref.cls)
  })

  it('color-codes added/modified/deleted distinctly', () => {
    // Smoke check that the three change statuses each get their own
    // Tailwind color class — a regression in the colour table would
    // be visible at a glance.
    const added = fileStatusBadge('added')
    const modified = fileStatusBadge('modified')
    const deleted = fileStatusBadge('deleted')
    expect(added.cls).toContain('emerald')
    expect(modified.cls).toContain('sky')
    expect(deleted.cls).toContain('rose')
    // And they don't all share the same class.
    expect(added.cls).not.toBe(modified.cls)
    expect(modified.cls).not.toBe(deleted.cls)
  })
})

describe('format.js — fileStatusLabel', () => {
  it('returns a localised label for a known status', () => {
    // The exact string is locale-table-owned; just assert it's
    // *some* non-empty, non-key string and changes when the locale
    // changes.
    const en = fileStatusLabel('added', 'en')
    const zh = fileStatusLabel('added', 'zh')
    expect(en).toBeTruthy()
    expect(zh).toBeTruthy()
    expect(en).not.toBe(zh)
    expect(en).not.toBe('added')  // not the raw id
  })

  it('returns the raw id when the i18n table is missing the key', () => {
    // Useful so the UI shows "refactor" or whatever custom id the
    // engine might invent later, instead of `files.statusRefactor`.
    expect(fileStatusLabel('totally_unknown', 'en')).toBe('totally_unknown')
  })
})


// --- groupFilesByFolder / listFolderPaths (I7) -----------------------

describe('format.js — groupFilesByFolder', () => {
  it('returns an empty root for an empty / missing list', () => {
    expect(groupFilesByFolder([]).files).toEqual([])
    expect(groupFilesByFolder([]).folders.size).toBe(0)
    expect(groupFilesByFolder(null).files).toEqual([])
  })

  it('keeps root-level files at the root', () => {
    const files = [{ path: 'README.md' }, { path: 'LICENSE' }]
    const root = groupFilesByFolder(files)
    expect(root.files).toHaveLength(2)
    expect(root.folders.size).toBe(0)
  })

  it('nests files under their containing folder', () => {
    const files = [
      { path: 'src/server.py' },
      { path: 'src/client.py' },
      { path: 'tests/test_server.py' },
    ]
    const root = groupFilesByFolder(files)
    expect(root.files).toHaveLength(0)
    expect(root.folders.size).toBe(2)
    const src = root.folders.get('src')
    expect(src.files).toHaveLength(2)
    expect(src.files[0].name).toBe('client.py')
    const tests = root.folders.get('tests')
    expect(tests.files).toHaveLength(1)
  })

  it('handles deeply nested paths and sorts folders alphabetically', () => {
    const files = [
      { path: 'src/api/v2/handler.py' },
      { path: 'src/api/v1/handler.py' },
      { path: 'src/api/handler.py' },
    ]
    const root = groupFilesByFolder(files)
    const src = root.folders.get('src')
    const api = src.folders.get('api')
    expect(api.path).toBe('src/api')
    // v1, v2, and the bare handler — three children: two folders
    // (v1, v2) and one file (handler.py).
    expect(api.folders.size).toBe(2)
    expect(api.files).toHaveLength(1)
    const childNames = Array.from(api.folders.keys())
    expect(childNames).toEqual(['v1', 'v2'])
    expect(api.folders.get('v1').files[0].path).toBe('src/api/v1/handler.py')
  })

  it('sorts files by status then path within a folder', () => {
    // The renderer relies on this order so the user sees added
    // files first, then modified, then deleted, then unchanged.
    const files = [
      { path: 'src/z.py', status: 'unchanged' },
      { path: 'src/a.py', status: 'added' },
      { path: 'src/m.py', status: 'modified' },
      { path: 'src/b.py', status: 'added' },
    ]
    const root = groupFilesByFolder(files)
    const src = root.folders.get('src')
    expect(src.files.map((f) => f.path)).toEqual([
      'src/a.py',
      'src/b.py',
      'src/m.py',
      'src/z.py',
    ])
  })
})

describe('format.js — listFolderPaths', () => {
  it('returns a pre-order list of folder paths', () => {
    const root = groupFilesByFolder([
      { path: 'src/a.py' },
      { path: 'src/api/v1/b.py' },
    ])
    const paths = listFolderPaths(root)
    expect(paths).toEqual(['', 'src', 'src/api', 'src/api/v1'])
  })
})

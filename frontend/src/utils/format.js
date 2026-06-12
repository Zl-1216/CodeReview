// Small formatting helpers.

import { translate } from '../i18n/messages.js'

// Static (non-localized) color + weight metadata. The display label is
// computed at render time via `severityLabel` / `categoryLabel`, so the
// Chinese locale doesn't have to fork the META shape.
export const SEVERITY_META = {
  critical: { color: 'red', weight: 4 },
  high: { color: 'orange', weight: 3 },
  medium: { color: 'amber', weight: 2 },
  low: { color: 'yellow', weight: 1 },
  info: { color: 'sky', weight: 0 },
}

export const CATEGORY_META = {
  bug: { icon: '🐞' },
  security: { icon: '🔒' },
  performance: { icon: '⚡' },
  style: { icon: '🎨' },
  best_practice: { icon: '✨' },
  documentation: { icon: '📝' },
}

export const SEVERITY_ORDER = ['critical', 'high', 'medium', 'low', 'info']

export const CATEGORY_ORDER = ['bug', 'security', 'performance', 'style', 'best_practice', 'documentation']

// Locale-aware display labels. Falls back through zh → en (handled in
// translate()), so a partially-translated locale never shows the raw
// key. The category id is `best_practice` (snake_case) but the i18n
// key is `label.bestPractice` (camelCase) — map here so callers can
// pass the natural id straight through. Unknown ids return the bare
// input so the UI shows "refactor" or whatever custom id the engine
// might invent later, instead of `label.refactor`.
export function severityLabel(s, locale) {
  const out = translate(locale, `label.${s}`)
  return out === `label.${s}` ? s : out
}

export function categoryLabel(c, locale) {
  const i18nKey = c === 'best_practice' ? 'label.bestPractice' : `label.${c}`
  const out = translate(locale, i18nKey)
  return out === i18nKey ? c : out
}

export function severityRank(s) {
  return SEVERITY_META[s]?.weight ?? -1
}

export function formatDateTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function formatRelative(iso, locale) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const diff = (Date.now() - d.getTime()) / 1000
  const isZh = locale === 'zh'
  // Keep the unit suffixes short — the "ago" / "前" particle goes at
  // the end in Chinese but the number and unit are otherwise identical.
  if (diff < 60) {
    const n = Math.max(0, Math.floor(diff))
    return isZh ? `${n} 秒前` : `${n}s ago`
  }
  if (diff < 3600) return isZh ? `${Math.floor(diff / 60)} 分钟前` : `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return isZh ? `${Math.floor(diff / 3600)} 小时前` : `${Math.floor(diff / 3600)}h ago`
  return isZh ? `${Math.floor(diff / 86400)} 天前` : `${Math.floor(diff / 86400)}d ago`
}

export function formatBytes(n) {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(2)} MB`
}

export function formatDuration(ms) {
  if (ms == null) return ''
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

// File change-status metadata. Drives the colour/icon in the file
// overview and the per-file badges in ReviewPanel. The label is
// fetched via the i18n table (files.statusAdded / Modified / ...)
// so the locale switches automatically; this table only carries
// the visual / ordering data.
export const FILE_STATUS_META = {
  added: { color: 'emerald', icon: '+', weight: 0, isChange: true },
  modified: { color: 'sky', icon: '~', weight: 1, isChange: true },
  deleted: { color: 'rose', icon: '−', weight: 2, isChange: true },
  renamed: { color: 'amber', icon: '→', weight: 3, isChange: true },
  unchanged: { color: 'gray', icon: '·', weight: 4, isChange: false },
}

export const FILE_STATUS_ORDER = ['added', 'modified', 'renamed', 'deleted', 'unchanged']

// Returns the badge props (Tailwind class + a11y label) for a file
// status. `meta` may be missing for legacy rows (status field was
// added later) — fall back to a neutral gray "unchanged" so the UI
// doesn't render an unstyled chip.
export function fileStatusBadge(status) {
  const m = FILE_STATUS_META[status] || FILE_STATUS_META.unchanged
  const clsByColor = {
    emerald: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800/50',
    sky: 'bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-300 border-sky-200 dark:border-sky-800/50',
    rose: 'bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-300 border-rose-200 dark:border-rose-800/50',
    amber: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300 border-amber-200 dark:border-amber-800/50',
    gray: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300 border-gray-200 dark:border-gray-700',
  }
  return {
    icon: m.icon,
    cls: `inline-flex items-center justify-center w-5 h-5 rounded font-mono text-xs font-semibold border ${clsByColor[m.color] || clsByColor.gray}`,
  }
}

// Locale-aware status label; falls back to the raw id.
export function fileStatusLabel(status, locale) {
  if (!status) return ''
  const out = translate(locale, `files.status${status[0].toUpperCase()}${status.slice(1)}`)
  return out.startsWith('files.status') ? status : out
}

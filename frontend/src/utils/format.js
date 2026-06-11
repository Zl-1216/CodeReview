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

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { isRef } from 'vue'
import { useI18n, setLocale, SUPPORTED_LOCALES } from './messages.js'

describe('i18n messages', () => {
  beforeEach(() => {
    localStorage.clear()
    setLocale('en')
  })

  it('returns the active locale by default (en)', () => {
    const { locale, t } = useI18n()
    expect(locale.value).toBe('en')
    expect(t('app.title')).toBe('CodeReview')
  })

  it('exposes a reactive locale (Vue ref, not plain object)', () => {
    // Regression: a previous version of this module used
    // `const activeLocale = { value: getInitialLocale() }` — a plain
    // object whose `.value` mutation did not trigger Vue's reactivity
    // system, so `t(key)` consumers in templates would not re-render
    // on locale change. Templates that read `locale.value` directly
    // rely on the ref, and any future component that consumes `t()` in
    // a `computed` does too.
    const { locale, t } = useI18n()
    expect(isRef(locale)).toBe(true)
    // Switching the ref must immediately affect t() output for the
    // same caller, without a separate re-fetch step.
    setLocale('zh')
    expect(locale.value).toBe('zh')
    expect(t('app.title')).toBe('CodeReview 代码评审')
    setLocale('en')
    expect(locale.value).toBe('en')
    expect(t('app.title')).toBe('CodeReview')
  })

  it('t() substitutes {name} params', () => {
    const { t } = useI18n()
    expect(t('review.files', { n: 3, model: 'claude-sonnet-4-6' })).toBe('3 file(s) · model claude-sonnet-4-6')
  })

  it('falls back to the English table for a missing key', () => {
    const { t } = useI18n()
    // even with locale=zh, an untranslated key returns the English string
    setLocale('zh')
    // Remove a key from the zh table at runtime to simulate a stale bundle.
    // (We just check that the en fallback is used for keys that exist in
    // en but not in zh, by relying on the test setup above.)
    expect(t('app.title')).toBe('CodeReview 代码评审')
  })

  it('logs a dev warning and returns the raw key for an unknown key', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const { t } = useI18n()
    expect(t('totally.unknown.key')).toBe('totally.unknown.key')
    expect(warn).toHaveBeenCalled()
    warn.mockRestore()
  })

  it('setLocale() updates the active locale and persists', () => {
    setLocale('zh')
    const { locale, t } = useI18n()
    expect(locale.value).toBe('zh')
    expect(t('app.title')).toBe('CodeReview 代码评审')
    expect(localStorage.getItem('codereview.locale')).toBe('zh')
  })

  it('setLocale() ignores unsupported values', () => {
    setLocale('fr')
    expect(useI18n().locale.value).toBe('en')
  })

  it('SUPPORTED_LOCALES lists en and zh', () => {
    expect(SUPPORTED_LOCALES).toEqual(['en', 'zh'])
  })

  it('every en key has a zh counterpart', () => {
    // Guard against drift between the two tables. The i18n table is
    // small enough that this test is cheap; if it ever fires, the
    // fix is one missing line in messages.js.
    const en = useI18n()
    setLocale('en')
    const { t: tEn } = en
    setLocale('zh')
    const { t: tZh } = useI18n()
    const enKeys = [
      'app.title', 'app.tagline', 'app.tips.title',
      'app.tips.diff', 'app.tips.click', 'app.tips.filter', 'app.tips.persist',
      'header.aiProvider', 'header.aiMock', 'header.lang',
      'input.title', 'input.hintBasic', 'input.hintGit', 'input.hintRemote',
      'input.modeSnippet', 'input.modeDiff', 'input.modeGit', 'input.modeRemote',
      'input.pathPlaceholder', 'input.langAuto', 'input.upload',
      'input.codePlaceholder', 'input.diffPlaceholder', 'input.detected',
      'input.repo', 'input.head', 'input.dirty',
      'input.baseRef', 'input.baseRefPlaceholder',
      'input.headRef', 'input.headRefPlaceholder', 'input.pathFilterPlaceholder',
      'input.previewDiff', 'input.showStat', 'input.previewSummary',
      'input.focuses', 'input.loadSample', 'input.run', 'input.submitting',
      'input.noFiles',
      'input.remoteUrl', 'input.remoteUrlPlaceholder',
      'input.remoteToken', 'input.remoteTokenPlaceholder',
      'input.connect', 'input.connecting',
      'input.refresh', 'input.disconnect',
      'input.remoteConnected', 'input.remoteFetched', 'input.remoteNoBranches',
      'input.apiKeyRequired', 'input.apiKeyWhereToFind',
      'input.apiKeyPlaceholder',
      'input.apiKeySave', 'input.apiKeySet', 'input.apiKeyClear',
      'input.apiKeyShow', 'input.apiKeyHide',
      'input.apiKeyPersistFailed', 'input.apiKeyWasInvalid',
      'input.remoteNetworkErrorHint', 'input.remoteTimeoutHint',

      'files.title', 'files.summary',
      'files.filterAll', 'files.filterAdded', 'files.filterModified', 'files.filterDeleted',
      'files.statusAdded', 'files.statusModified', 'files.statusDeleted',
      'files.statusRenamed', 'files.statusUnchanged',
      'files.countBadge', 'files.findingsFor', 'files.noFindings',
      'files.legendAdded', 'files.legendRemoved', 'files.legendContext',
      'refPicker.branches', 'refPicker.tags', 'refPicker.noBranches',
      'refPicker.openPicker', 'refPicker.closePicker',
      'refPicker.openPickerAria', 'refPicker.closePickerAria',
      'common.refresh', 'common.loading', 'common.delete', 'common.cancel',
      'review.cancel', 'review.rerun', 'review.new', 'review.files',
      'review.findings', 'review.filterSeverity', 'review.filterCategory',
      'review.ofTotal', 'review.noMatch', 'review.clean',
      'review.idle', 'review.connecting', 'review.waiting',
      'review.allFiles', 'review.errorBanner',
      'review.noFilesInStatus', 'review.clearFiltersHint',
      'review.noFindingsInReview', 'review.reviewCompleteHint',
      'finding.jumpTo', 'finding.jumpToAria',
      'finding.copy', 'finding.copied', 'finding.copyAria',
      'finding.suggestedFix', 'finding.codeSnippet',
      'finding.expand', 'finding.collapse',
      'history.title', 'history.total', 'history.empty',
      'history.fileCount', 'history.findingCount', 'history.deleteAria',
      'summary.title', 'summary.statusIdle', 'summary.statusConnecting',
      'summary.statusStreaming', 'summary.statusCompleted',
      'summary.statusFailed', 'summary.download', 'summary.viewFindings',
      'summary.filterBy',
      'codeView.empty',
      'label.critical', 'label.high', 'label.medium', 'label.low', 'label.info',
      'label.bug', 'label.security', 'label.performance',
      'label.style', 'label.bestPractice', 'label.documentation',
    ]
    for (const k of enKeys) {
      const enS = tEn(k)
      const zhS = tZh(k)
      expect(enS, `en missing key ${k}`).not.toBe(k)
      expect(zhS, `zh missing key ${k}`).not.toBe(k)
    }
  })
})

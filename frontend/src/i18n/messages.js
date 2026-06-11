// Lightweight i18n. Two flat string tables (en / zh) and a small
// composable that returns a `t(key)` function. Skip vue-i18n to avoid
// the ~8 KB gzipped dependency — we only need a few dozen keys.
//
// To add a new key: add an entry to BOTH tables. The 'every key has a
// counterpart' test in messages.test.js catches drift at test time.
//
import { ref } from 'vue'

const STORAGE_KEY = 'codereview.locale'

export const SUPPORTED_LOCALES = ['en', 'zh']

const messages = {
  en: {
    // app
    'app.title': 'CodeReview',
    'app.tagline': 'Streaming reviews · severity-ranked findings · review history',
    'app.tips.title': 'Tips',
    'app.tips.diff': 'Use the "Git diff" mode to paste output of',
    'app.tips.click': 'Click a finding to jump to the line in the code preview above the list.',
    'app.tips.filter': 'Filter by severity from the summary card.',
    'app.tips.persist': 'Reviews are stored in SQLite and survive restarts.',

    // header
    'header.aiProvider': 'AI provider: {model}',
    'header.aiMock': 'Mock review engine (set ANTHROPIC_API_KEY for real reviews)',
    'header.lang': 'Language',

    // input panel
    'input.title': 'Submit a review',
    'input.hintBasic': 'Paste code or a unified diff.',
    'input.hintGit': 'Paste code, drop a file, paste a diff, or compare branches.',
    'input.hintRemote': 'Compare a user-supplied remote repo by URL.',
    'input.modeSnippet': 'Code snippet',
    'input.modeDiff': 'Git diff',
    'input.modeGit': 'Branches',
    'input.modeRemote': 'Remote',
    'input.pathPlaceholder': 'Path, e.g. src/server.py',
    'input.langAuto': 'Auto-detect',
    'input.upload': 'Upload file',
    'input.codePlaceholder': 'Paste code here…',
    'input.diffPlaceholder': 'Paste unified diff (output of `git diff`)…',
    'input.detected': 'Detected {n} file(s):',
    'input.repo': 'Repo:',
    'input.head': 'HEAD:',
    'input.dirty': 'uncommitted changes',
    'input.baseRef': 'Base ref',
    'input.baseRefPlaceholder': 'main, v1.0.0, abc123…',
    'input.headRef': 'Head ref',
    'input.headRefPlaceholder': 'feature, my-branch…',
    'input.pathFilterPlaceholder': 'Optional path filter, e.g. src/server/',
    'input.previewDiff': 'Preview diff',
    'input.showStat': 'Show stat',
    'input.previewSummary': '{n} file(s) · {bin} binary skipped',
    'input.focuses': 'Review focuses',
    'input.loadSample': 'Load sample',
    'input.run': 'Run review',
    'input.submitting': 'Submitting…',
    'input.noFiles': 'No files to review',

    // remote git mode
    'input.remoteUrl': 'Remote URL',
    'input.remoteUrlPlaceholder': 'https://github.com/owner/repo.git',
    'input.remoteToken': 'Access token (optional, private repos)',
    'input.remoteTokenPlaceholder': 'ghp_… / glpat-… / xoxb-…',
    'input.connect': 'Connect',
    'input.connecting': 'Cloning…',
    'input.refresh': 'Refresh',
    'input.disconnect': 'Disconnect',
    'input.remoteConnected': 'Connected to {name}',
    'input.remoteFetched': 'Last fetched: {when}',
    'input.remoteNoBranches': 'No branches fetched yet',

    // API key (REVIEW_API_KEY)
    'input.apiKeyRequired': 'This server requires an API key (REVIEW_API_KEY). Enter it once — it will be remembered in this browser.',
    'input.apiKeyPlaceholder': 'Paste your API key…',
    'input.apiKeySave': 'Save',
    'input.apiKeySet': 'API key saved ✓',
    'input.apiKeyClear': 'Clear',

    // ref picker
    'refPicker.branches': 'Branches',
    'refPicker.tags': 'Tags',
    'refPicker.noBranches': 'No branches loaded',
    'refPicker.openPicker': 'Pick a ref',
    'refPicker.closePicker': 'Close picker',
    'refPicker.openPickerAria': 'Open {label} picker',
    'refPicker.closePickerAria': 'Close {label} picker',

    // common
    'common.refresh': 'Refresh',
    'common.loading': 'Loading…',
    'common.delete': 'Delete',
    'common.cancel': 'Cancel',

    // review
    'review.cancel': 'Cancel',
    'review.rerun': 'Re-run',
    'review.new': 'New review',
    'review.files': '{n} file(s) · model {model}',
    'review.findings': 'Findings',
    'review.filterSeverity': 'Severity: {sev} · ',
    'review.filterCategory': 'Category: {cat} · ',
    'review.ofTotal': '{visible} of {total} finding(s)',
    'review.noMatch': 'No findings match the active filter.',
    'review.clean': 'No findings — the code looks clean.',
    'review.idle': 'Submit a review to see findings here.',
    'review.connecting': 'Connecting to review stream…',
    'review.waiting': 'Waiting for findings…',
    'review.allFiles': 'All files',
    'review.errorBanner': 'Review error',

    // finding card
    'finding.jumpTo': 'Jump to line',
    'finding.jumpToAria': 'Jump to line in code preview',
    'finding.copy': 'Copy',
    'finding.copied': 'Copied',
    'finding.copyAria': 'Copy code snippet',
    'finding.suggestedFix': 'Suggested fix',

    // history
    'history.title': 'History',
    'history.total': '{n} past review(s)',
    'history.empty': 'No past reviews yet.',
    'history.fileCount': '{n} file(s)',
    'history.findingCount': '{n} finding(s)',
    'history.deleteAria': 'Delete review {title}',

    // summary card
    'summary.title': 'Review summary',
    'summary.statusIdle': 'Idle',
    'summary.statusConnecting': 'Connecting…',
    'summary.statusStreaming': 'Reviewing…',
    'summary.statusCompleted': 'Completed',
    'summary.statusFailed': 'Failed',
    'summary.download': 'Download as Markdown',
    'summary.filterBy': 'Filter by {cat}',

    // code view
    'codeView.empty': 'No content',

    // severity / category labels (rendered through format.js helpers)
    'label.critical': 'Critical',
    'label.high': 'High',
    'label.medium': 'Medium',
    'label.low': 'Low',
    'label.info': 'Info',
    'label.bug': 'Bug',
    'label.security': 'Security',
    'label.performance': 'Performance',
    'label.style': 'Style',
    'label.bestPractice': 'Best practice',
    'label.documentation': 'Docs',
  },
  zh: {
    'app.title': 'CodeReview 代码评审',
    'app.tagline': '流式评审 · 按严重度排序的发现 · 历史记录',
    'app.tips.title': '小贴士',
    'app.tips.diff': '使用「Git diff」模式粘贴',
    'app.tips.click': '点击 finding 跳到上方代码视图对应行。',
    'app.tips.filter': '在 Summary 卡片中按严重度过滤。',
    'app.tips.persist': '评审记录持久化在 SQLite,重启后仍在。',

    'header.aiProvider': 'AI 提供方: {model}',
    'header.aiMock': 'Mock 评审引擎 (设置 ANTHROPIC_API_KEY 以启用真实评审)',
    'header.lang': '语言',

    'input.title': '提交评审',
    'input.hintBasic': '粘贴代码或 unified diff。',
    'input.hintGit': '粘贴代码、拖入文件、粘贴 diff,或对比分支。',
    'input.hintRemote': '通过 URL 对比用户提供的远程仓库。',
    'input.modeSnippet': '代码片段',
    'input.modeDiff': 'Git diff',
    'input.modeGit': '分支',
    'input.modeRemote': '远程',
    'input.pathPlaceholder': '路径,例如 src/server.py',
    'input.langAuto': '自动检测',
    'input.upload': '上传文件',
    'input.codePlaceholder': '在此粘贴代码…',
    'input.diffPlaceholder': '粘贴 unified diff (即 `git diff` 的输出)…',
    'input.detected': '识别到 {n} 个文件:',
    'input.repo': '仓库:',
    'input.head': 'HEAD:',
    'input.dirty': '有未提交变更',
    'input.baseRef': '基准 ref',
    'input.baseRefPlaceholder': 'main, v1.0.0, abc123…',
    'input.headRef': '目标 ref',
    'input.headRefPlaceholder': 'feature, my-branch…',
    'input.pathFilterPlaceholder': '可选路径过滤,例如 src/server/',
    'input.previewDiff': '预览 diff',
    'input.showStat': '显示 stat',
    'input.previewSummary': '{n} 个文件 · 跳过 {bin} 个二进制',
    'input.focuses': '评审重点',
    'input.loadSample': '加载示例',
    'input.run': '运行评审',
    'input.submitting': '提交中…',
    'input.noFiles': '没有可评审的文件',

    'input.remoteUrl': '远程仓库 URL',
    'input.remoteUrlPlaceholder': 'https://github.com/owner/repo.git',
    'input.remoteToken': '访问令牌 (可选,私有仓库)',
    'input.remoteTokenPlaceholder': 'ghp_… / glpat-… / xoxb-…',
    'input.connect': '连接',
    'input.connecting': '克隆中…',
    'input.refresh': '刷新',
    'input.disconnect': '断开',
    'input.remoteConnected': '已连接 {name}',
    'input.remoteFetched': '上次拉取: {when}',
    'input.remoteNoBranches': '尚未拉取任何分支',

    'input.apiKeyRequired': '该服务器要求 API key (REVIEW_API_KEY)。输入一次,本浏览器会记住。',
    'input.apiKeyPlaceholder': '粘贴 API key…',
    'input.apiKeySave': '保存',
    'input.apiKeySet': '已保存 API key ✓',
    'input.apiKeyClear': '清除',

    'refPicker.branches': '分支',
    'refPicker.tags': '标签',
    'refPicker.noBranches': '尚未加载分支',
    'refPicker.openPicker': '选择 ref',
    'refPicker.closePicker': '关闭选择器',
    'refPicker.openPickerAria': '打开 {label} 选择器',
    'refPicker.closePickerAria': '关闭 {label} 选择器',

    'common.refresh': '刷新',
    'common.loading': '加载中…',
    'common.delete': '删除',
    'common.cancel': '取消',

    'review.cancel': '取消',
    'review.rerun': '重新运行',
    'review.new': '新建评审',
    'review.files': '{n} 个文件 · 模型 {model}',
    'review.findings': '评审结果',
    'review.filterSeverity': '严重度: {sev} · ',
    'review.filterCategory': '类别: {cat} · ',
    'review.ofTotal': '{visible} / {total} 条',
    'review.noMatch': '没有符合当前过滤条件的 finding。',
    'review.clean': '没有发现 — 代码看起来很干净。',
    'review.idle': '提交评审后,结果会显示在这里。',
    'review.connecting': '正在连接评审流…',
    'review.waiting': '等待 finding…',
    'review.allFiles': '所有文件',
    'review.errorBanner': '评审错误',

    'finding.jumpTo': '跳到行',
    'finding.jumpToAria': '跳到上方代码视图对应行',
    'finding.copy': '复制',
    'finding.copied': '已复制',
    'finding.copyAria': '复制代码片段',
    'finding.suggestedFix': '建议修复',

    'history.title': '历史记录',
    'history.total': '{n} 条历史评审',
    'history.empty': '暂无历史评审。',
    'history.fileCount': '{n} 个文件',
    'history.findingCount': '{n} 条 finding',
    'history.deleteAria': '删除评审 {title}',

    'summary.title': '评审摘要',
    'summary.statusIdle': '空闲',
    'summary.statusConnecting': '连接中…',
    'summary.statusStreaming': '评审中…',
    'summary.statusCompleted': '已完成',
    'summary.statusFailed': '失败',
    'summary.download': '下载为 Markdown',
    'summary.filterBy': '按 {cat} 过滤',

    'codeView.empty': '暂无内容',

    'label.critical': '严重',
    'label.high': '高',
    'label.medium': '中',
    'label.low': '低',
    'label.info': '提示',
    'label.bug': '缺陷',
    'label.security': '安全',
    'label.performance': '性能',
    'label.style': '风格',
    'label.bestPractice': '最佳实践',
    'label.documentation': '文档',
  },
}

function getInitialLocale() {
  if (typeof localStorage === 'undefined') return 'zh'
  const stored = localStorage.getItem(STORAGE_KEY)
  if (stored && SUPPORTED_LOCALES.includes(stored)) return stored
  if (typeof navigator !== 'undefined' && navigator.language) {
    if (navigator.language.toLowerCase().startsWith('zh')) return 'zh'
    if (navigator.language.toLowerCase().startsWith('en')) return 'en'
  }
  // Default to Chinese — the README and primary audience are zh.
  return 'zh'
}

const activeLocale = ref(getInitialLocale())

function translate(locale, key, params) {
  const table = messages[locale] || messages.zh
  let s = table[key]
  if (s === undefined) {
    if (import.meta?.env?.DEV) {
      console.warn(`[i18n] missing key "${key}" in locale "${locale}"`)
    }
    // Fall back through zh → en so a partially-translated locale
    // never shows the raw key.
    s = messages.zh[key] || messages.en[key] || key
  }
  if (!params) return s
  return s.replace(/\{(\w+)\}/g, (_, k) => (params[k] !== undefined ? String(params[k]) : `{${k}}`))
}

export { translate }

export function setLocale(loc) {
  if (!SUPPORTED_LOCALES.includes(loc)) return
  activeLocale.value = loc
  try {
    localStorage.setItem(STORAGE_KEY, loc)
  } catch {
    // ignore — private mode, etc
  }
}

export function useI18n() {
  return {
    locale: activeLocale,
    t: (key, params) => translate(activeLocale.value, key, params),
    setLocale,
  }
}

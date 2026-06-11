// Build a Markdown export of a finished review. Pure function over the
// review object returned by GET /api/reviews/{id} — no DOM access, easy
// to unit-test.

const SEVERITY_RANK = { critical: 4, high: 3, medium: 2, low: 1, info: 0 }
const SEVERITY_ORDER = ['critical', 'high', 'medium', 'low', 'info']

function safeFilename(title) {
  return (title || 'review').replace(/[^a-z0-9_-]+/gi, '_')
}

export function reviewToMarkdown(review) {
  if (!review) return ''
  const lines = []
  lines.push(`# ${review.title || 'Code review'}`)
  lines.push('')
  lines.push(`- **Status:** ${review.status}`)
  lines.push(`- **Model:** ${review.model}`)
  lines.push(`- **Files:** ${review.file_count}`)
  lines.push(`- **Created:** ${review.created_at}`)
  if (review.duration_ms != null) lines.push(`- **Duration:** ${review.duration_ms}ms`)
  lines.push('')
  if (review.summary) {
    lines.push('## Summary')
    lines.push('')
    lines.push(review.summary.overall_assessment)
    lines.push('')
    const sev = review.summary.by_severity || {}
    lines.push('| Severity | Count |')
    lines.push('|----------|-------|')
    for (const s of SEVERITY_ORDER) {
      lines.push(`| ${s} | ${sev[s] || 0} |`)
    }
    lines.push('')
  }
  if (review.findings?.length) {
    lines.push('## Findings')
    lines.push('')
    const sorted = [...review.findings].sort((a, b) => {
      return (SEVERITY_RANK[b.severity] || 0) - (SEVERITY_RANK[a.severity] || 0)
    })
    for (const f of sorted) {
      const loc = f.line_start
        ? ` (L${f.line_start}${f.line_end && f.line_end !== f.line_start ? '–' + f.line_end : ''})`
        : ''
      lines.push(`### [${f.severity.toUpperCase()}] ${f.title}`)
      lines.push('')
      lines.push(`- **File:** \`${f.file_path}\`${loc}`)
      lines.push(`- **Category:** ${f.category}`)
      lines.push('')
      lines.push(f.detail)
      if (f.code_snippet) {
        lines.push('')
        lines.push('```')
        lines.push(f.code_snippet)
        lines.push('```')
      }
      if (f.suggestion) {
        lines.push('')
        lines.push('**Suggested fix:**')
        lines.push('')
        lines.push('```')
        lines.push(f.suggestion)
        lines.push('```')
      }
      lines.push('')
    }
  }
  return lines.join('\n')
}

export function downloadReviewMarkdown(review) {
  const md = reviewToMarkdown(review)
  const blob = new Blob([md], { type: 'text/markdown' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${safeFilename(review?.title)}.md`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

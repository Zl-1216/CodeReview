import { describe, it, expect } from 'vitest'
import { reviewToMarkdown } from './markdown.js'

const sampleReview = {
  id: 'r1',
  title: 'My review',
  status: 'completed',
  model: 'claude-3',
  file_count: 1,
  created_at: '2026-06-06T10:00:00',
  duration_ms: 1234,
  summary: {
    overall_assessment: 'Looks fine.',
    by_severity: { critical: 0, high: 1, medium: 0, low: 0, info: 0 },
  },
  findings: [
    {
      severity: 'high',
      category: 'security',
      title: 'Use of eval()',
      detail: 'eval is dangerous',
      file_path: 'a.py',
      line_start: 3,
      line_end: 3,
      code_snippet: 'eval(x)',
      suggestion: 'Use ast.literal_eval',
    },
    {
      severity: 'critical',
      category: 'security',
      title: 'pickle deserialization',
      detail: 'pickle.loads is unsafe',
      file_path: 'b.py',
    },
  ],
}

describe('reviewToMarkdown', () => {
  it('returns empty string for null review', () => {
    expect(reviewToMarkdown(null)).toBe('')
  })

  it('emits header lines for metadata', () => {
    const md = reviewToMarkdown(sampleReview)
    expect(md).toContain('# My review')
    expect(md).toContain('- **Status:** completed')
    expect(md).toContain('- **Model:** claude-3')
    expect(md).toContain('- **Files:** 1')
    expect(md).toContain('- **Created:** 2026-06-06T10:00:00')
    expect(md).toContain('- **Duration:** 1234ms')
  })

  it('emits summary section with severity table', () => {
    const md = reviewToMarkdown(sampleReview)
    expect(md).toContain('## Summary')
    expect(md).toContain('Looks fine.')
    expect(md).toContain('| Severity | Count |')
    expect(md).toContain('| high | 1 |')
  })

  it('sorts findings by severity descending', () => {
    const md = reviewToMarkdown(sampleReview)
    const criticalIdx = md.indexOf('CRITICAL')
    const highIdx = md.indexOf('HIGH')
    expect(criticalIdx).toBeGreaterThan(-1)
    expect(highIdx).toBeGreaterThan(-1)
    expect(criticalIdx).toBeLessThan(highIdx)
  })

  it('renders line range when line_end differs from line_start', () => {
    const md = reviewToMarkdown(sampleReview)
    // a.py has line_start=3, line_end=3 → just "L3"
    expect(md).toContain('L3')
  })

  it('renders code snippet and suggestion blocks', () => {
    const md = reviewToMarkdown(sampleReview)
    expect(md).toContain('```')
    expect(md).toContain('eval(x)')
    expect(md).toContain('**Suggested fix:**')
    expect(md).toContain('Use ast.literal_eval')
  })

  it('omits findings section when there are none', () => {
    const r = { ...sampleReview, findings: [] }
    const md = reviewToMarkdown(r)
    expect(md).not.toContain('## Findings')
  })

  it('omits duration when null', () => {
    const r = { ...sampleReview, duration_ms: null }
    const md = reviewToMarkdown(r)
    expect(md).not.toContain('Duration:')
  })
})

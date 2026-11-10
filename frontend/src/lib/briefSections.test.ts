// Tests for the brief markdown splitter: narrative / References / Also noticed.
import { describe, expect, it } from 'vitest'
import { splitBrief } from './briefSections'

// A current-format brief: lead, theme sections, References, Also noticed.
const FULL = [
  'Lead paragraph about the day.',
  '',
  '## Agentic AI',
  '',
  'Theme prose citing [A](card:1).',
  '',
  '## References',
  '',
  '- [First card](card:1) — Feed A',
  '- [Second card](card:2) — Feed B',
  '',
  '## Also noticed',
  '',
  '- [Third](card:3)',
  '- [Fourth](card:4)',
].join('\n')

describe('splitBrief', () => {
  it('splits a full brief into narrative, references, and also-noticed', () => {
    const parts = splitBrief(FULL)
    expect(parts.narrative).toContain('Lead paragraph')
    expect(parts.narrative).toContain('## Agentic AI')
    expect(parts.narrative).not.toContain('## References')
    expect(parts.references).toContain('[First card](card:1)')
    expect(parts.references).not.toContain('## Also noticed')
    expect(parts.alsoNoticed).toContain('[Third](card:3)')
    expect(parts.alsoCount).toBe(2)
  })

  it('keeps the section headings out of the extracted bodies', () => {
    const parts = splitBrief(FULL)
    expect(parts.references).not.toContain('## References')
    expect(parts.alsoNoticed).not.toContain('## Also noticed')
  })

  it('tolerates a brief without an Also noticed section', () => {
    const md = 'Lead.\n\n## References\n\n- [One](card:1)\n'
    const parts = splitBrief(md)
    expect(parts.narrative).toBe('Lead.')
    expect(parts.references).toContain('[One](card:1)')
    expect(parts.alsoNoticed).toBeNull()
    expect(parts.alsoCount).toBe(0)
  })

  it('treats an old-format brief (no ## sections) as pure narrative', () => {
    const md = '# Daily Brief\n\nJust prose with [A](card:1).'
    const parts = splitBrief(md)
    expect(parts.narrative).toBe(md)
    expect(parts.references).toBeNull()
    expect(parts.alsoNoticed).toBeNull()
    expect(parts.alsoCount).toBe(0)
  })

  it('does not split on "References" mentioned mid-line or in prose', () => {
    const md = 'The paper has ## References inline.\nSee references below.'
    const parts = splitBrief(md)
    expect(parts.narrative).toBe(md)
    expect(parts.references).toBeNull()
  })

  it('counts numbered items in Also noticed too', () => {
    const md = '## References\n\n- [A](card:1)\n\n## Also noticed\n\n1. [B](card:2)\n2. [C](card:3)\n3. [D](card:4)'
    expect(splitBrief(md).alsoCount).toBe(3)
  })

  it('splits at the LAST References heading if a theme reused the name', () => {
    // The renderer always appends the real References tail last; a stray theme heading
    // "## References" earlier must not steal the split.
    const md = [
      'Lead.',
      '',
      '## References',
      '',
      'A theme the model happened to title "References" citing [A](card:1).',
      '',
      '## References',
      '',
      '- [First](card:1) — Feed A',
    ].join('\n')
    const parts = splitBrief(md)
    expect(parts.narrative).toContain('A theme the model happened to title')
    expect(parts.references).toContain('[First](card:1)')
    expect(parts.references).not.toContain('A theme the model')
  })

  it('collapses Also noticed on a listed-only brief with no References', () => {
    // A window with only low-relevance items has an Also-noticed tail but no References.
    const md = 'Nothing crossed the relevance bar for a full write-up.\n\n## Also noticed\n\n- [A](card:1)\n- [B](card:2)'
    const parts = splitBrief(md)
    expect(parts.narrative).toBe('Nothing crossed the relevance bar for a full write-up.')
    expect(parts.references).toBeNull()
    expect(parts.alsoNoticed).toContain('[A](card:1)')
    expect(parts.alsoCount).toBe(2)
  })
})

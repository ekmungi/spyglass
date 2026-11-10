// Tests for the collapsible reader Summary panel: rich render, default-open, toggle, empty.
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SummaryPanel } from './SummaryPanel'

describe('SummaryPanel', () => {
  it('renders the summary as rich Markdown and is expanded by default', () => {
    render(<SummaryPanel summary={'**key** point'} />)
    const toggle = screen.getByRole('button', { name: /summary/i })
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('key').tagName).toBe('STRONG')
  })

  it('collapses then re-expands when the header is clicked', () => {
    render(<SummaryPanel summary={'**key** point'} />)
    const toggle = screen.getByRole('button', { name: /summary/i })

    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('key')).toBeNull()

    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('key').tagName).toBe('STRONG')
  })

  it('renders nothing when the summary is empty', () => {
    const { container } = render(<SummaryPanel summary={''} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders un-enriched HTML summaries as clean plain text, not literal tags', () => {
    // RSS blurbs (pre-enrichment) carry HTML; react-markdown would otherwise emit the
    // tag characters as literal text. They must be stripped to readable plain text.
    const { container } = render(<SummaryPanel summary={'<p>Amazon ships <b>AI chips</b></p>'} />)
    expect(container.textContent).toContain('Amazon ships AI chips')
    expect(container.textContent).not.toContain('<p>')
    expect(container.textContent).not.toContain('<b>')
  })

  it('does not flatten a multi-line Markdown summary into one line', () => {
    // An enriched (Markdown) summary must keep its list structure — stripHtml would
    // collapse the newlines, so the HTML gate must NOT touch clean Markdown.
    render(<SummaryPanel summary={'- first\n- second'} />)
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
  })
})

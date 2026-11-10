// Tests for the in-dashboard briefing reader.
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { BriefingModal } from './BriefingModal'

describe('BriefingModal', () => {
  it('renders the markdown briefing with headings and tables', () => {
    const markdown = '# Findings\n\nSome **bold** text.\n\n| a | b |\n|---|---|\n| 1 | 2 |'
    render(<BriefingModal title="Sync engines" markdown={markdown} onClose={() => {}} />)
    expect(screen.getByRole('heading', { name: 'Findings' })).toBeInTheDocument()
    expect(screen.getByText('bold')).toBeInTheDocument()
    expect(screen.getByRole('table')).toBeInTheDocument()
  })

  it('closes via the close button', () => {
    const onClose = vi.fn()
    render(<BriefingModal title="T" markdown="body" onClose={onClose} />)
    fireEvent.click(screen.getByRole('button', { name: /close/i }))
    expect(onClose).toHaveBeenCalled()
  })

  it('renders through the shared reader-markdown styles', () => {
    // Migrated to the shared Markdown component so prose (margins, headings, bullets)
    // is styled consistently instead of relying on the undefined .briefing-body class.
    const { container } = render(
      <BriefingModal title="T" markdown={'# Heading\n\nbody'} onClose={() => {}} />,
    )
    expect(container.querySelector('.reader-markdown')).not.toBeNull()
  })
})

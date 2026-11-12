// Tests for PaperRow: a paper's addresses become links only when they are plain web addresses.
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { PaperResult } from '../../api/types'
import { PaperRow } from './PaperRow'

afterEach(cleanup)

function paper(over: Partial<PaperResult>): PaperResult {
  return { title: 'A paper', authors: [], published: null, url: 'https://arxiv.org/abs/1', pdf_url: 'https://arxiv.org/pdf/1', abstract: '', why: null, signal: null, item_id: null, ...over }
}

const row = (p: PaperResult) => (
  <ul>
    <PaperRow paper={p} itemId={null} adding={false} addError={null} onAdd={() => undefined} />
  </ul>
)

describe('PaperRow addresses', () => {
  it('links web addresses', () => {
    render(row(paper({})))
    expect(screen.getByRole('link', { name: 'Open' })).toHaveAttribute('href', 'https://arxiv.org/abs/1')
    expect(screen.getByRole('link', { name: 'PDF' })).toHaveAttribute('href', 'https://arxiv.org/pdf/1')
  })

  it('shows an unsafe address as plain text with no link', () => {
    render(row(paper({ url: 'javascript:alert(1)', pdf_url: 'data:text/html,x' })))
    expect(screen.queryByRole('link')).toBeNull()
    expect(screen.getByText('javascript:alert(1)')).toBeInTheDocument()
  })
})

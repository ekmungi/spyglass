// Citations in a feed answer: [#123] becomes a small link named by the item's headline; no other
// bracket text becomes a link, and a link a model writes itself never becomes an internal one.
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { AnswerMarkdown } from './answerMarkdown'
import { citedIds } from './citations'

const labels: Record<number, string> = { 12: 'Capsule endoscopy gets a clearance', 40: 'A trial of AI triage' }
const label = (id: number) => labels[id] ?? null

beforeEach(() => window.history.replaceState(null, '', '/#/feed'))
afterEach(cleanup)

describe('citedIds', () => {
  it('lists each cited id once, in the order first cited', () => {
    expect(citedIds('A [#40] and B [#12], again [#40] and [#7].')).toEqual([40, 12, 7])
  })

  it('ignores anything that is not exactly [#number]', () => {
    expect(citedIds('[#12, #40] [# 5] [#x] [12] (#9) [#0] [#]')).toEqual([])
  })
})

describe('AnswerMarkdown with citations', () => {
  it('shows a known headline as the link text and opens the reader on click', () => {
    render(<AnswerMarkdown citeLabel={label}>{'The clearance matters [#12].'}</AnswerMarkdown>)
    const link = screen.getByRole('link', { name: 'Capsule endoscopy gets a clearance' })
    expect(link).toHaveAttribute('href', '#/item/12')
    expect(link).toHaveAttribute('title', 'Capsule endoscopy gets a clearance')
    expect(link).not.toHaveAttribute('target')
    fireEvent.click(link)
    expect(window.location.hash).toBe('#/item/12')
  })

  it('falls back to "#id" when the headline is not known', () => {
    render(<AnswerMarkdown citeLabel={label}>{'See [#99].'}</AnswerMarkdown>)
    expect(screen.getByRole('link', { name: '#99' })).toHaveAttribute('href', '#/item/99')
  })

  it('links markers inside lists and emphasis, but not inside code', () => {
    render(<AnswerMarkdown citeLabel={label}>{'- first [#12]\n- **second [#40]**\n\n`[#12]` stays code'}</AnswerMarkdown>)
    expect(screen.getAllByRole('link').map((link) => link.getAttribute('href'))).toEqual(['#/item/12', '#/item/40'])
    expect(screen.getByText('[#12]', { selector: 'code' })).toBeInTheDocument()
  })

  it('renders every other bracket form as plain text', () => {
    const { container } = render(<AnswerMarkdown citeLabel={label}>{'[#12, #40] and [note] and [12] and [#abc] and [#]'}</AnswerMarkdown>)
    expect(container.querySelectorAll('a')).toHaveLength(0)
    expect(container.textContent).toContain('[#12, #40]')
  })

  it('does not turn a link the model wrote itself into an item link', () => {
    const { container } = render(<AnswerMarkdown citeLabel={label}>{'[click here](#/item/12) and [site](https://example.org/x)'}</AnswerMarkdown>)
    const links = [...container.querySelectorAll('a')]
    expect(links).toHaveLength(1)
    expect(links[0]).toHaveAttribute('href', 'https://example.org/x')
    expect(container.textContent).toContain('click here')
  })

  it('leaves markers as text when no citation labels are given (answers about one article)', () => {
    const { container } = render(<AnswerMarkdown>{'Plain [#12] text'}</AnswerMarkdown>)
    expect(container.querySelectorAll('a')).toHaveLength(0)
    expect(container.textContent).toBe('Plain [#12] text')
  })
})

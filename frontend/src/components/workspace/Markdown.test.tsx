// Tests for the shared Markdown renderer: rich elements + the reader-markdown wrapper.
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { Markdown } from './Markdown'

describe('Markdown', () => {
  it('renders bold text as <strong>', () => {
    render(<Markdown>{'hello **world**'}</Markdown>)
    expect(screen.getByText('world').tagName).toBe('STRONG')
  })

  it('renders a bullet list as <ul> with items', () => {
    render(<Markdown>{'- first\n- second'}</Markdown>)
    const items = screen.getAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(items[0]).toHaveTextContent('first')
  })

  it('renders a link with its href', () => {
    render(<Markdown>{'see [the docs](https://example.com)'}</Markdown>)
    const link = screen.getByRole('link', { name: 'the docs' })
    expect(link).toHaveAttribute('href', 'https://example.com')
  })

  it('wraps content in the reader-markdown class', () => {
    const { container } = render(<Markdown>{'plain text'}</Markdown>)
    expect(container.querySelector('.reader-markdown')).not.toBeNull()
  })

  // --- card:<id> link scheme ---

  it('lets card: hrefs survive and routes clicks to onCardLink', () => {
    const onCardLink = vi.fn()
    render(<Markdown onCardLink={onCardLink}>{'open [A card](card:12)'}</Markdown>)
    const link = screen.getByRole('link', { name: 'A card' })
    expect(link).toHaveAttribute('href', 'card:12')
    fireEvent.click(link)
    expect(onCardLink).toHaveBeenCalledWith(12)
  })

  it('keeps external links untouched when onCardLink is set', () => {
    const onCardLink = vi.fn()
    render(<Markdown onCardLink={onCardLink}>{'see [docs](https://example.com)'}</Markdown>)
    const link = screen.getByRole('link', { name: 'docs' })
    expect(link).toHaveAttribute('href', 'https://example.com')
    fireEvent.click(link)
    expect(onCardLink).not.toHaveBeenCalled()
  })

  it('sanitizes card: hrefs when no onCardLink handler is given', () => {
    render(<Markdown>{'open [A card](card:12)'}</Markdown>)
    // Without a handler the default urlTransform strips the unknown protocol.
    expect(screen.getByText('A card')).not.toHaveAttribute('href', 'card:12')
  })
})

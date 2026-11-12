// Tests for the Menu popover: it opens, and it is kept inside the window when it would run off an edge.
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Menu } from './Menu'

afterEach(() => vi.restoreAllMocks())

function renderMenu() {
  render(<Menu label="Engines" items={[{ id: 'a', label: 'Claude Code', onSelect: () => undefined }]} trigger={<button type="button">Engine</button>} />)
  fireEvent.click(screen.getByRole('button', { name: 'Engine' }))
  return screen.getByRole('menu', { name: 'Engines' })
}

describe('Menu', () => {
  it('opens a list of items and leaves one that fits where it is', () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1000 })
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ left: 300, right: 560, top: 0, bottom: 0, width: 260, height: 0, x: 300, y: 0, toJSON: () => ({}) })
    const list = renderMenu()
    expect(list).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: 'Claude Code' })).toBeInTheDocument()
    expect(list.style.transform).toBe('')
  })

  it('slides left when the list would run off the right edge of the window', () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1000 })
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ left: 800, right: 1060, top: 0, bottom: 0, width: 260, height: 0, x: 800, y: 0, toJSON: () => ({}) })
    const list = renderMenu()
    // 1060 is 68px past the 8px margin at 992.
    expect(list.style.transform).toBe('translateX(-68px)')
  })

  it('slides right when the list would run off the left edge', () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1000 })
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ left: -30, right: 230, top: 0, bottom: 0, width: 260, height: 0, x: -30, y: 0, toJSON: () => ({}) })
    const list = renderMenu()
    expect(list.style.transform).toBe('translateX(38px)')
  })
})

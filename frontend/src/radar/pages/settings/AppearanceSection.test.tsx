// Tests for Settings > Appearance: the controls apply at once, stay in sync with the rail's theme
// toggle, show each font in its own typeface and list the groups in the agreed order.
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { initAppearance } from '../../appearance/appearanceStore'
import { Rail } from '../../shell/Rail'
import { AppearanceSection } from './AppearanceSection'
import { APPLY_DELAY_MS } from './TextWidthSlider'

const root = document.documentElement

beforeEach(() => {
  window.localStorage.clear()
  root.removeAttribute('style')
  root.removeAttribute('data-theme')
  initAppearance()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('AppearanceSection', () => {
  it('lists the reading and interface fonts in groups, each sample set in its own typeface', () => {
    render(<AppearanceSection />)
    const reading = screen.getByRole('group', { name: 'Reading font' })
    const names = within(reading).getAllByRole('radio').map((radio) => radio.getAttribute('aria-label'))
    // The default alone, then "From your notes theme", then "More" (Newsreader is there now).
    expect(names).toEqual(['Fira Sans', 'Source Sans 3', 'Nunito Sans', 'Newsreader', 'Source Serif 4', 'Literata', 'Lora', 'Crimson Pro', 'Sans (same as interface)'])
    expect(within(reading).getByRole('radio', { name: 'Fira Sans' })).toBeChecked()
    expect(within(reading).getByText('From your notes theme')).toBeInTheDocument()
    expect(within(reading).getByText('More')).toBeInTheDocument()
    const lora = within(reading).getByRole('radio', { name: 'Lora' }).closest('label')?.querySelector('.rst-font__text') as HTMLElement
    expect(lora.style.fontFamily).toContain('Lora Variable')
    expect(within(lora).getByText(/Regulators clear the first/)).toBeInTheDocument()
    const ui = screen.getByRole('group', { name: 'Interface font' })
    expect(within(ui).getAllByRole('radio').map((radio) => radio.getAttribute('aria-label'))).toEqual(['Fira Sans', 'Source Sans 3', 'Nunito Sans', 'Inter', 'Figtree', 'DM Sans', 'IBM Plex Sans', 'Geist', 'System'])
    expect(within(ui).getByRole('radio', { name: 'Fira Sans' })).toBeChecked()
  })

  it('applies a reading font, an interface font and a text size at once and remembers them', () => {
    render(<AppearanceSection />)
    fireEvent.click(screen.getByRole('radio', { name: 'Literata' }))
    expect(root.style.getPropertyValue('--font-serif')).toContain('Literata')
    fireEvent.click(within(screen.getByRole('group', { name: 'Interface font' })).getByRole('radio', { name: 'Inter' }))
    expect(root.style.getPropertyValue('--font-sans')).toContain('Inter')
    fireEvent.click(screen.getByRole('radio', { name: 'Large' }))
    expect(root.style.getPropertyValue('--type-scale')).toBe('1.12')
    expect(window.localStorage.getItem('radar.font.reading')).toBe('"literata"')
    expect(window.localStorage.getItem('radar.font.ui')).toBe('"inter"')
    expect(window.localStorage.getItem('radar.textsize')).toBe('"large"')
  })

  it('shows the text width as a word and a number', () => {
    render(<AppearanceSection />)
    const slider = screen.getByRole('slider', { name: 'Text width' })
    expect(slider).toHaveAttribute('min', '560')
    expect(slider).toHaveAttribute('max', '1100')
    expect(screen.getByTestId('text-width-value')).toHaveTextContent('Medium · 680px')
  })

  it('changes only the label while the slider is dragged, and applies the width after release', () => {
    vi.useFakeTimers()
    render(<AppearanceSection />)
    const slider = screen.getByRole('slider', { name: 'Text width' })
    fireEvent.pointerDown(slider)
    fireEvent.change(slider, { target: { value: '900' } })
    fireEvent.change(slider, { target: { value: '1000' } })
    expect(screen.getByTestId('text-width-value')).toHaveTextContent('Extra wide · 1000px')
    expect(slider).toHaveAttribute('aria-valuetext', 'Extra wide · 1000px')
    act(() => {
      vi.advanceTimersByTime(1000)
    })
    // Still dragging: the page keeps its width and nothing is stored.
    expect(root.style.getPropertyValue('--measure')).toBe('680px')
    expect(window.localStorage.getItem('radar.textwidth')).toBeNull()
    fireEvent.pointerUp(window)
    act(() => {
      vi.advanceTimersByTime(APPLY_DELAY_MS - 10)
    })
    expect(root.style.getPropertyValue('--measure')).toBe('680px')
    act(() => {
      vi.advanceTimersByTime(20)
    })
    expect(root.style.getPropertyValue('--measure')).toBe('1000px')
    expect(window.localStorage.getItem('radar.textwidth')).toBe('1000')
    expect(screen.getByTestId('text-width-value')).toHaveTextContent('Extra wide · 1000px')
  })

  it('debounces keyboard changes and applies the last one', () => {
    vi.useFakeTimers()
    render(<AppearanceSection />)
    const slider = screen.getByRole('slider', { name: 'Text width' })
    fireEvent.change(slider, { target: { value: '700' } })
    act(() => {
      vi.advanceTimersByTime(APPLY_DELAY_MS - 50)
    })
    fireEvent.change(slider, { target: { value: '720' } })
    act(() => {
      vi.advanceTimersByTime(APPLY_DELAY_MS - 50)
    })
    expect(root.style.getPropertyValue('--measure')).toBe('680px')
    expect(screen.getByTestId('text-width-value')).toHaveTextContent('Medium · 720px')
    act(() => {
      vi.advanceTimersByTime(60)
    })
    expect(root.style.getPropertyValue('--measure')).toBe('720px')
    expect(window.localStorage.getItem('radar.textwidth')).toBe('720')
  })

  it('does not apply a stale width after leaving the page during the delay', () => {
    vi.useFakeTimers()
    const { unmount } = render(<AppearanceSection />)
    fireEvent.change(screen.getByRole('slider', { name: 'Text width' }), { target: { value: '960' } })
    unmount()
    act(() => {
      vi.advanceTimersByTime(APPLY_DELAY_MS * 4)
    })
    expect(root.style.getPropertyValue('--measure')).toBe('680px')
    expect(window.localStorage.getItem('radar.textwidth')).toBeNull()
  })

  it('resets everything with "Reset to defaults"', () => {
    render(<AppearanceSection />)
    fireEvent.click(screen.getByRole('radio', { name: 'Dark' }))
    fireEvent.click(screen.getByRole('radio', { name: 'Lora' }))
    fireEvent.click(within(screen.getByRole('group', { name: 'Interface font' })).getByRole('radio', { name: 'Geist' }))
    fireEvent.change(screen.getByRole('slider', { name: 'Text width' }), { target: { value: '900' } })
    fireEvent.click(screen.getByRole('button', { name: 'Reset to defaults' }))
    expect(screen.getByRole('radio', { name: 'Follow system' })).toBeChecked()
    expect(within(screen.getByRole('group', { name: 'Reading font' })).getByRole('radio', { name: 'Fira Sans' })).toBeChecked()
    expect(within(screen.getByRole('group', { name: 'Interface font' })).getByRole('radio', { name: 'Fira Sans' })).toBeChecked()
    expect(root.style.getPropertyValue('--font-serif')).toContain('"Fira Sans"')
    expect(screen.getByTestId('text-width-value')).toHaveTextContent('Medium · 680px')
    expect(root.hasAttribute('data-theme')).toBe(false)
  })

  it('drops a width still waiting to apply when everything is reset', () => {
    vi.useFakeTimers()
    render(<AppearanceSection />)
    fireEvent.change(screen.getByRole('slider', { name: 'Text width' }), { target: { value: '1000' } })
    fireEvent.click(screen.getByRole('button', { name: 'Reset to defaults' }))
    act(() => {
      vi.advanceTimersByTime(APPLY_DELAY_MS * 4)
    })
    expect(root.style.getPropertyValue('--measure')).toBe('680px')
    expect(screen.getByTestId('text-width-value')).toHaveTextContent('Medium · 680px')
  })

  it('stays in step with the rail toggle in both directions', () => {
    render(
      <>
        <Rail active="settings" />
        <AppearanceSection />
      </>,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Switch to dark theme' }))
    expect(screen.getByRole('radio', { name: 'Dark' })).toBeChecked()
    expect(root.getAttribute('data-theme')).toBe('dark')
    fireEvent.click(screen.getByRole('radio', { name: 'Light' }))
    expect(screen.getByRole('button', { name: 'Switch to dark theme' })).toBeInTheDocument()
  })
})

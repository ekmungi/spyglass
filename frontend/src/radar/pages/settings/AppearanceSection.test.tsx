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
  /** The labels of the entries of a menu, in order. */
  const entries = (menu: HTMLElement) => within(menu).getAllByRole('option').map((option) => option.textContent)

  it('offers each font choice as one menu with one sample, the samples set in the chosen typeface', () => {
    render(<AppearanceSection />)
    const reading = screen.getByRole('combobox', { name: 'Reading font' })
    // The default alone, then "From your notes theme", then "More" (Newsreader is there now).
    expect(entries(reading)).toEqual(['Fira Sans (default)', 'Source Sans 3', 'Nunito Sans', 'Newsreader', 'Source Serif 4', 'Literata', 'Lora', 'Crimson Pro', 'Sans (same as interface)'])
    expect(within(reading).getByRole('group', { name: 'From your notes theme' })).toBeInTheDocument()
    expect(within(reading).getByRole('group', { name: 'More' })).toBeInTheDocument()
    expect(reading).toHaveValue('fira-sans')
    const ui = screen.getByRole('combobox', { name: 'Interface font' })
    expect(entries(ui)).toEqual(['Fira Sans (default)', 'Source Sans 3', 'Nunito Sans', 'Inter', 'Figtree', 'DM Sans', 'IBM Plex Sans', 'Geist', 'System'])
    expect(ui).toHaveValue('fira-sans')
    // No radio per font any more: one sample under each menu, whatever the number of fonts.
    expect(screen.queryAllByRole('radio', { name: /Lora|Inter|Geist/ })).toHaveLength(0)
    const readingSample = within(screen.getByRole('group', { name: 'Reading font' })).getByText(/Regulators clear the first/).closest('.rst-font__sample') as HTMLElement
    expect(document.querySelectorAll('.rst-font__sample')).toHaveLength(2)
    expect(readingSample.style.fontFamily).toContain('Fira Sans')
    fireEvent.change(reading, { target: { value: 'lora' } })
    expect(readingSample.style.fontFamily).toContain('Lora Variable')
    expect(within(readingSample).getByText(/The trial covered 1,200 patients/)).toBeInTheDocument()
  })

  it('applies a reading font, an interface font and a text size at once and remembers them', () => {
    render(<AppearanceSection />)
    fireEvent.change(screen.getByRole('combobox', { name: 'Reading font' }), { target: { value: 'literata' } })
    expect(root.style.getPropertyValue('--font-serif')).toContain('Literata')
    fireEvent.change(screen.getByRole('combobox', { name: 'Interface font' }), { target: { value: 'inter' } })
    expect(root.style.getPropertyValue('--font-sans')).toContain('Inter')
    fireEvent.click(screen.getByRole('radio', { name: 'Large' }))
    expect(root.style.getPropertyValue('--type-scale')).toBe('1.12')
    expect(window.localStorage.getItem('radar.font.reading')).toBe('"literata"')
    expect(window.localStorage.getItem('radar.font.ui')).toBe('"inter"')
    expect(window.localStorage.getItem('radar.textsize')).toBe('"large"')
  })

  it('sets the reading font "Sans" in the interface font, in its sample too', () => {
    render(<AppearanceSection />)
    fireEvent.change(screen.getByRole('combobox', { name: 'Interface font' }), { target: { value: 'geist' } })
    fireEvent.change(screen.getByRole('combobox', { name: 'Reading font' }), { target: { value: 'sans' } })
    const sample = within(screen.getByRole('group', { name: 'Reading font' })).getByText(/Regulators clear the first/).closest('.rst-font__sample') as HTMLElement
    expect(sample.style.fontFamily).toContain('Geist')
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
    fireEvent.change(screen.getByRole('combobox', { name: 'Reading font' }), { target: { value: 'lora' } })
    fireEvent.change(screen.getByRole('combobox', { name: 'Interface font' }), { target: { value: 'geist' } })
    fireEvent.change(screen.getByRole('slider', { name: 'Text width' }), { target: { value: '900' } })
    fireEvent.click(screen.getByRole('button', { name: 'Reset to defaults' }))
    expect(screen.getByRole('radio', { name: 'Follow system' })).toBeChecked()
    expect(screen.getByRole('combobox', { name: 'Reading font' })).toHaveValue('fira-sans')
    expect(screen.getByRole('combobox', { name: 'Interface font' })).toHaveValue('fira-sans')
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

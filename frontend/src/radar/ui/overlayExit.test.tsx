// Tests for overlay exits: Menu, Dialog and the toast stack stay mounted, marked closed and inert,
// for their exit duration; a dialog that replaces another is marked as a hand-over.
import { act, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Dialog } from './Dialog'
import { Menu } from './Menu'
import { ToastViewport } from './Toast'
import { dismissToast, reconcileToasts, toast, type ToastMessage } from './toastStore'

function setDurations() {
  const style = document.documentElement.style
  style.setProperty('--dur-fast', '120ms')
  style.setProperty('--dur', '200ms')
  style.setProperty('--dur-slow', '280ms')
}

beforeEach(() => {
  vi.useFakeTimers()
  setDurations()
})

afterEach(() => {
  document.documentElement.removeAttribute('style')
  vi.useRealTimers()
})

describe('Menu exit', () => {
  it('keeps the closing list for --dur-fast, closed and inert, then removes it', () => {
    render(<Menu label="Actions" items={[{ id: 'a', label: 'Archive', onSelect: () => undefined }]} trigger={<button type="button">More</button>} />)
    fireEvent.click(screen.getByRole('button', { name: 'More' }))
    const list = screen.getByRole('menu', { name: 'Actions' })
    expect(list).toHaveAttribute('data-state', 'open')
    fireEvent.keyDown(list, { key: 'Escape' })
    expect(list).toHaveAttribute('data-state', 'closed')
    expect(list).toHaveAttribute('inert')
    expect(screen.getByRole('button', { name: 'More' })).toHaveAttribute('aria-expanded', 'false')
    act(() => vi.advanceTimersByTime(120))
    expect(list).not.toBeInTheDocument()
  })
})

describe('Dialog exit and hand-over', () => {
  function Host() {
    const [open, setOpen] = useState(true)
    return (
      <Dialog open={open} onClose={() => setOpen(false)} title="Add a link">
        <input aria-label="Web address" />
      </Dialog>
    )
  }

  it('keeps the closing dialog for --dur, closed and inert, then removes it', () => {
    render(<Host />)
    const backdrop = document.querySelector('.r-dialog-backdrop') as HTMLElement
    expect(backdrop).toHaveAttribute('data-state', 'open')
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(backdrop).toHaveAttribute('data-state', 'closed')
    expect(backdrop).toHaveAttribute('inert')
    act(() => vi.advanceTimersByTime(200))
    expect(document.querySelector('.r-dialog-backdrop')).toBeNull()
  })

  it('marks a dialog that replaces another in the same click as a hand-over', () => {
    function Doors() {
      const [door, setDoor] = useState<'link' | 'text'>('link')
      return door === 'link' ? (
        <Dialog open onClose={() => undefined} title="Add a link">
          <button type="button" onClick={() => setDoor('text')}>
            Paste the text
          </button>
        </Dialog>
      ) : (
        <section>
          <Dialog open onClose={() => undefined} title="Paste the text">
            <textarea aria-label="Text" />
          </Dialog>
        </section>
      )
    }
    render(<Doors />)
    expect(document.querySelector('.r-dialog-backdrop')).not.toHaveAttribute('data-swap')
    fireEvent.click(screen.getByRole('button', { name: 'Paste the text' }))
    expect(screen.getByRole('dialog', { name: 'Paste the text' })).toBeInTheDocument()
    expect(document.querySelector('.r-dialog-backdrop')).toHaveAttribute('data-swap', 'true')
  })
})

describe('toast stack', () => {
  const message = (id: number): ToastMessage => ({ id, message: `Toast ${id}`, tone: 'info' })

  it('marks a dismissed toast leaving and appends new ones in order', () => {
    const shown = reconcileToasts([], [message(1), message(2)], true)
    expect(reconcileToasts(shown, [message(2), message(3)], true)).toEqual([
      { item: message(1), leaving: true },
      { item: message(2), leaving: false },
      { item: message(3), leaving: false },
    ])
  })

  it('drops a dismissed toast at once when there is no exit to play', () => {
    const shown = reconcileToasts([], [message(1), message(2)], false)
    expect(reconcileToasts(shown, [message(2)], false)).toEqual([{ item: message(2), leaving: false }])
  })

  it('fades a dismissed toast for --dur-fast before removing it', () => {
    render(<ToastViewport />)
    let id = 0
    act(() => {
      id = toast('Saved for later')
    })
    const element = screen.getByText('Saved for later').closest('.r-toast') as HTMLElement
    expect(element).toHaveAttribute('data-state', 'open')
    act(() => dismissToast(id))
    expect(element).toHaveAttribute('data-state', 'closed')
    expect(element).toHaveAttribute('aria-hidden', 'true')
    act(() => vi.advanceTimersByTime(120))
    expect(screen.queryByText('Saved for later')).toBeNull()
  })
})

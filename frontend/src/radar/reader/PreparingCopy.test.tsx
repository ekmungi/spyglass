// Tests for the reader's "preparing" view: one message from the click until the copy is ready,
// and a way out when the wait runs long.
import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PREPARING_MESSAGE, PreparingCopy } from './PreparingCopy'

afterEach(() => {
  vi.useRealTimers()
})

describe('PreparingCopy', () => {
  it('waits before showing the message when asked to, with the status region already in place', async () => {
    vi.useFakeTimers()
    render(<PreparingCopy delayMs={400} />)
    expect(screen.getByRole('status')).not.toHaveTextContent(PREPARING_MESSAGE)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(399)
    })
    expect(screen.queryByText(PREPARING_MESSAGE)).not.toBeInTheDocument()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1)
    })
    expect(screen.getByRole('status')).toHaveTextContent(PREPARING_MESSAGE)
  })

  it('shows the preparing message as a status', () => {
    render(<PreparingCopy />)
    expect(PREPARING_MESSAGE).toBe('Preparing a clean copy and a summary of this article. The first time takes a few seconds.')
    expect(screen.getByRole('status')).toHaveTextContent(PREPARING_MESSAGE)
    expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument()
  })

  it('offers Try again when the wait is long', () => {
    const onRetry = vi.fn()
    render(<PreparingCopy slow onRetry={onRetry} />)
    expect(screen.getByText('This is taking longer than usual.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(onRetry).toHaveBeenCalledTimes(1)
  })
})

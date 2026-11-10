// Tests for the item code chip.
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ItemCode } from './ItemCode'

describe('ItemCode', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('copies the code without triggering the row behind it', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const onRow = vi.fn()
    render(
      <div onClick={onRow}>
        <ItemCode id={1042} />
      </div>,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Copy #1042' }))
    expect(writeText).toHaveBeenCalledWith('#1042')
    expect(onRow).not.toHaveBeenCalled()
    expect(await screen.findByText('Copied')).toBeInTheDocument()
  })
})

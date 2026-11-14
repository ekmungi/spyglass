// Tests for the row's Save for later toggle: where its tooltip opens.
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { ItemState } from '../api/types'
import { SaveButton } from './SaveButton'

const unsaved = { saved: false, opened: false, vote: null, from_user: false, captured_via: null, vault_path: null } as unknown as ItemState

describe('SaveButton', () => {
  it('keeps the tooltip above the button by default', () => {
    // Rows on Today and in the Feed have room above them, so their tooltip stays on top.
    render(<SaveButton id={7} base={unsaved} />)
    const tip = screen.getByRole('button', { name: 'Save for later' }).closest('.r-tip')
    expect(tip).not.toBeNull()
    expect(tip).not.toHaveClass('r-tip--bottom')
  })
})

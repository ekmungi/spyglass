// Tests for the To file view's manual control: File now leads, See the request stays quiet.
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { FileNowControl } from './FileNowControl'

describe('FileNowControl', () => {
  it('shows File now as a filled button and See the request as a quiet one', () => {
    render(<FileNowControl />)
    expect(screen.getByRole('button', { name: 'File now' })).toHaveClass('r-btn--primary')
    expect(screen.getByRole('button', { name: 'See the request' })).toHaveClass('r-btn--quiet')
  })
})

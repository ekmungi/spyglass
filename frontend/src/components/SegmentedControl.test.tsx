// Tests for the segmented control: option rendering, active state, change events.
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { SegmentedControl } from './SegmentedControl'

const options = [
  { value: 'workspace', label: 'Workspace' },
  { value: 'activity', label: 'Activity' },
]

describe('SegmentedControl', () => {
  it('renders one button per option', () => {
    render(<SegmentedControl options={options} value="workspace" onChange={() => {}} />)
    expect(screen.getByRole('button', { name: 'Workspace' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Activity' })).toBeInTheDocument()
  })

  it('marks the active segment with aria-pressed', () => {
    render(<SegmentedControl options={options} value="activity" onChange={() => {}} />)
    expect(screen.getByRole('button', { name: 'Activity' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(screen.getByRole('button', { name: 'Workspace' })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
  })

  it('reports the clicked value', () => {
    const onChange = vi.fn()
    render(<SegmentedControl options={options} value="workspace" onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: 'Activity' }))
    expect(onChange).toHaveBeenCalledWith('activity')
  })
})

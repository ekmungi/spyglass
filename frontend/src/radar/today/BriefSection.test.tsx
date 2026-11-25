// Tests for one section of Today and its slider: five stories and then four per page in the top
// section and three elsewhere, the count and its tooltip, the two arrows, the ring on an unpicked
// story, a brief composed before unpicked stories were stored, the page following the keyboard, and
// an arrow turn moving the keyboard selection onto the new page.
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { BriefSection as Section, BriefSectionKey } from '../api/types'
import { resetItemState } from '../state/itemState'
import { BriefSection } from './BriefSection'
import { makeStories } from './testStories'

const RING = 'Not picked for today. Thumbs up tells Spyglass that it should have been.'

/**
 * A section with `picked` stories (item ids from 1) and, unless `unpicked` is left out, that many
 * unpicked stories under `more` (item ids from 101) and `pool` stories judged.
 */
function section(key: BriefSectionKey, picked: number, unpicked?: number, pool?: number): Section {
  return {
    key,
    title: '',
    note: 'Three picked from many',
    stories: makeStories(picked, 1),
    ...(unpicked === undefined ? {} : { more: makeStories(unpicked, 101), pool }),
  }
}

/** The headlines of the stories on screen, in order. */
const headlines = () => Array.from(document.querySelectorAll('.r-story__headline'), (element) => element.textContent)
const next = () => screen.getByRole('button', { name: 'More stories in this section' })
const previous = () => screen.getByRole('button', { name: 'Previous stories in this section' })

afterEach(() => {
  cleanup()
  resetItemState()
})

describe('BriefSection', () => {
  it('shows five stories on the first page of the top section and four on later pages', () => {
    render(<BriefSection section={section('top', 6, 9, 40)} />)
    expect(headlines()).toEqual(['Story 1', 'Story 2', 'Story 3', 'Story 4', 'Story 5'])
    expect(screen.getByText('1-5 of 15')).toBeInTheDocument()
    fireEvent.click(next())
    expect(headlines()).toEqual(['Story 6', 'Story 101', 'Story 102', 'Story 103'])
    expect(screen.getByText('6-9 of 15')).toBeInTheDocument()
  })

  it('shows three stories per page in every other section, with the count of the page', () => {
    render(<BriefSection section={section('notable', 4, 11, 15)} />)
    expect(headlines()).toEqual(['Story 1', 'Story 2', 'Story 3'])
    fireEvent.click(next())
    expect(headlines()).toEqual(['Story 4', 'Story 101', 'Story 102'])
    expect(screen.getByText('4-6 of 15')).toBeInTheDocument()
  })

  it('shows no count and no arrows when the picked and unpicked stories fit on one page', () => {
    render(<BriefSection section={section('papers', 2, 1, 3)} />)
    expect(headlines()).toEqual(['Story 1', 'Story 2', 'Story 101'])
    expect(screen.queryByRole('button', { name: 'More stories in this section' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Previous stories in this section' })).toBeNull()
    expect(screen.queryByText(/ of 3$/)).toBeNull()
    expect(screen.getByText('Three picked from many')).toBeInTheDocument()
  })

  it('shows every story without arrows for a brief composed before unpicked stories were stored', () => {
    render(<BriefSection section={section('notable', 8)} />)
    expect(headlines()).toHaveLength(8)
    expect(screen.queryByRole('button', { name: 'More stories in this section' })).toBeNull()
    expect(screen.queryByRole('img', { name: RING })).toBeNull()
    expect(screen.getByText('Three picked from many')).toBeInTheDocument()
  })

  it('moves on with "More stories" and back with "Previous stories", each marked disabled at its end', () => {
    render(<BriefSection section={section('papers', 3, 4, 7)} />)
    expect(previous()).toHaveAttribute('aria-disabled', 'true')
    expect(next()).not.toHaveAttribute('aria-disabled')
    fireEvent.click(next())
    expect(headlines()).toEqual(['Story 101', 'Story 102', 'Story 103'])
    expect(previous()).not.toHaveAttribute('aria-disabled')
    fireEvent.click(next())
    // A page that holds one story names its position alone.
    expect(headlines()).toEqual(['Story 104'])
    expect(screen.getByText('7 of 7')).toBeInTheDocument()
    expect(next()).toHaveAttribute('aria-disabled', 'true')
    fireEvent.click(previous())
    expect(headlines()).toEqual(['Story 101', 'Story 102', 'Story 103'])
    expect(screen.getByText('4-6 of 7')).toBeInTheDocument()
  })

  it('keeps an arrow focusable at its end, where a click does nothing', () => {
    render(<BriefSection section={section('papers', 3, 1, 4)} />)
    next().focus()
    fireEvent.click(next())
    expect(headlines()).toEqual(['Story 101'])
    expect(next()).not.toBeDisabled()
    fireEvent.click(next())
    expect(headlines()).toEqual(['Story 101'])
    expect(document.activeElement).toBe(next())
    fireEvent.click(previous())
    fireEvent.click(previous())
    expect(headlines()).toEqual(['Story 1', 'Story 2', 'Story 3'])
  })

  it('moves the keyboard selection to the first story of the new page when it was in this section', () => {
    const onSelect = vi.fn()
    const view = render(<BriefSection section={section('papers', 3, 4, 7)} start={10} selected={11} onSelect={onSelect} />)
    fireEvent.click(next())
    expect(onSelect).toHaveBeenCalledWith(13)
    // The page holds the newly selected story already, so following it does not turn again.
    view.rerender(<BriefSection section={section('papers', 3, 4, 7)} start={10} selected={13} onSelect={onSelect} />)
    expect(headlines()).toEqual(['Story 101', 'Story 102', 'Story 103'])
    expect(document.querySelector('[data-row-index="13"]')).toHaveClass('is-selected')
  })

  it('leaves a selection in another section alone when an arrow turns the page', () => {
    const onSelect = vi.fn()
    render(<BriefSection section={section('papers', 3, 4, 7)} start={10} selected={2} onSelect={onSelect} />)
    fireEvent.click(next())
    expect(headlines()).toEqual(['Story 101', 'Story 102', 'Story 103'])
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('says on the count how many stories were judged when the Feed holds more', () => {
    render(<BriefSection section={section('notable', 4, 11, 37)} />)
    const tip = screen.getByText('1-3 of 15').closest('.r-tip')
    expect(tip?.querySelector('.r-tip__bubble')?.textContent).toBe(
      '37 stories were judged for this section today. The 15 best are here, and the Feed has the rest.',
    )
  })

  it('gives the count no tooltip when the slider holds every story judged', () => {
    render(<BriefSection section={section('notable', 4, 11, 15)} />)
    expect(screen.getByText('1-3 of 15').closest('.r-tip')).toBeNull()
  })

  it('draws the ring with its accessible text on unpicked stories only', () => {
    render(<BriefSection section={section('top', 1, 5, 6)} />)
    const rows = screen.getAllByRole('listitem')
    expect(within(rows[0]).queryByRole('img', { name: RING })).toBeNull()
    for (const row of rows.slice(1)) expect(within(row).getByRole('img', { name: RING })).toBeInTheDocument()
  })

  it('spans the lead story across the top section on its first page only', () => {
    const { container, unmount } = render(<BriefSection section={section('top', 6, 3, 9)} />)
    expect(container.querySelector('.r-brief__list')).toHaveClass('r-brief__list--lead')
    fireEvent.click(next())
    expect(container.querySelector('.r-brief__list')).not.toHaveClass('r-brief__list--lead')
    unmount()
    const other = render(<BriefSection section={section('papers', 3, 3, 6)} />)
    expect(other.container.querySelector('.r-brief__list')).not.toHaveClass('r-brief__list--lead')
  })

  it('numbers its rows from `start` and turns to the page of the story the keyboard selects', () => {
    const view = render(<BriefSection section={section('papers', 3, 6, 9)} start={10} selected={-1} />)
    expect(document.querySelector('[data-row-index="10"]')).not.toBeNull()
    view.rerender(<BriefSection section={section('papers', 3, 6, 9)} start={10} selected={17} />)
    expect(headlines()).toEqual(['Story 104', 'Story 105', 'Story 106'])
    const row = document.querySelector('[data-row-index="17"]') as HTMLElement
    expect(row).toHaveClass('is-selected')
    expect(document.activeElement).toBe(row.querySelector('a'))
  })
})

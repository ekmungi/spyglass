// Tests for the summary block: the reader's own note, and not repeating a paper's abstract.
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { ItemDetail } from '../api/types'
import { closeClaudeDialog, getClaudeDialog } from '../claude/claudeStore'
import { SummaryBlock } from './SummaryBlock'

const ABSTRACT = 'We study self-supervised pretraining for surgical video and compare seven recipes across seven downstream tasks.'

function detail(over: Partial<ItemDetail> = {}, html = `<h2>Abstract</h2><p>${ABSTRACT}</p><p>1 Introduction</p>`): ItemDetail {
  return {
    id: 1,
    headline: 'A paper',
    why: null,
    key_points: [],
    summary: null,
    state: { saved: false, opened: false, vote: null, from_user: false, captured_via: null, vault_path: null },
    reader: { kind: 'paper', html, status: 'ok', word_count: 100, error: null },
    ...over,
  } as unknown as ItemDetail
}

describe('SummaryBlock note', () => {
  it('shows "Your note:" with the reader\'s own words when the item carries one', () => {
    const state = { saved: false, opened: false, vote: null, from_user: true, captured_via: 'dashboard', vault_path: null, note: 'Check the licence before we use it.' }
    render(<SummaryBlock detail={detail({ state })} />)
    expect(screen.getByText('Your note:')).toBeInTheDocument()
    expect(screen.getByText(/Check the licence before we use it\./)).toBeInTheDocument()
  })

  it('reads the note from user_note on the item detail', () => {
    render(<SummaryBlock detail={detail({ user_note: 'Ask the team about the dataset.' })} />)
    expect(screen.getByText('Your note:')).toBeInTheDocument()
    expect(screen.getByText(/Ask the team about the dataset\./)).toBeInTheDocument()
  })

  it('shows no note line when there is none, and nothing at all for an empty block', () => {
    const { container } = render(<SummaryBlock detail={detail()} />)
    expect(screen.queryByText('Your note:')).not.toBeInTheDocument()
    expect(container).toBeEmptyDOMElement()
  })
})

describe('SummaryBlock abstract', () => {
  it('leaves the abstract out of the summary when the document opens with it, and keeps the key points', () => {
    render(<SummaryBlock detail={detail({ key_points: ['Seven recipes were compared.'], summary: ABSTRACT, why: 'Useful for your detectors.' })} />)
    expect(screen.queryByText(ABSTRACT)).not.toBeInTheDocument()
    expect(screen.getByText('Seven recipes were compared.')).toBeInTheDocument()
    expect(screen.getByText('Useful for your detectors.')).toBeInTheDocument()
  })

  it('does not repeat an abstract that appears as the only key point', () => {
    render(<SummaryBlock detail={detail({ key_points: [ABSTRACT], why: 'Useful for your detectors.' })} />)
    expect(screen.queryByText(ABSTRACT)).not.toBeInTheDocument()
    expect(screen.getByText('Useful for your detectors.')).toBeInTheDocument()
  })

  it('still shows a snippet that is not in the document', () => {
    render(<SummaryBlock detail={detail({ summary: 'A different one-line description of what the paper is about overall.' })} />)
    expect(screen.getByText(/different one-line description/)).toBeInTheDocument()
  })
})

describe('SummaryBlock filed line', () => {
  it('shows one calm line with the project and the date, and the path in small text', () => {
    render(<SummaryBlock detail={detail({ filed: { path: 'Imaging AI/Resources/Polyp study.md', project: 'Imaging AI', at: '2026-11-12T08:00:00Z' } })} />)
    expect(screen.getByText('Filed · Imaging AI · 12 Nov 2026')).toBeInTheDocument()
    expect(screen.getByText('Imaging AI/Resources/Polyp study.md')).toBeInTheDocument()
  })

  it('says "your vault" when it was filed without a project', () => {
    render(<SummaryBlock detail={detail({ filed: { path: 'Inbox/Note.md', project: null, at: '2026-11-12T08:00:00Z' } })} />)
    expect(screen.getByText('Filed · your vault · 12 Nov 2026')).toBeInTheDocument()
  })

  it('shows no filed line for an item that was not filed', () => {
    render(<SummaryBlock detail={detail({ filed: null, why: 'Because.' })} />)
    expect(screen.queryByText(/^Filed/)).not.toBeInTheDocument()
  })
})

describe('SummaryBlock Open in Claude Code', () => {
  const sentIn = { saved: false, opened: false, vote: null, from_user: true, captured_via: 'slack', vault_path: null, note: 'For the endoscopy project.' }

  afterEach(() => closeClaudeDialog())

  it('offers a quiet action beside the note of an item the reader sent in, which opens the dialog on File into a project', () => {
    render(<SummaryBlock detail={detail({ id: 31, state: sentIn })} />)
    expect(screen.getByText('Your note:')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Open in Claude Code…' }))
    expect(getClaudeDialog()).toMatchObject({ itemId: 31 })
  })

  it('offers it even when the reader wrote no note', () => {
    render(<SummaryBlock detail={detail({ state: { ...sentIn, note: null } })} />)
    expect(screen.getByRole('button', { name: 'Open in Claude Code…' })).toBeInTheDocument()
  })

  it('offers nothing on an item the reader did not send in (it is in the More menu instead)', () => {
    render(<SummaryBlock detail={detail({ why: 'Because.' })} />)
    expect(screen.queryByRole('button', { name: 'Open in Claude Code…' })).not.toBeInTheDocument()
  })
})

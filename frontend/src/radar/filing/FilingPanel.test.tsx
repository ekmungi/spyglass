// Tests for the To file view's background-run groups: the status line in each sample state, the
// open questions with one Submit, the plan with strike toggles and one Approve, and Filed recently
// with Open in Obsidian. The sample service stands in for the real one; a wrapper records calls.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { setFetchForTesting } from '../api/transport'
import { clearFeedCache } from '../feed/useFeed'
import { clearResourceCache } from '../hooks/useResource'
import { mockFetch, resetMockState } from '../mock'
import { FeedPage } from '../pages/FeedPage'
import { setFilingConfigured } from '../state/filingConfigured'
import { resetFilingState } from '../state/filingState'
import { dismissToast, subscribeToasts, type ToastMessage } from '../ui/toastStore'
import { APPROVED_TOAST } from './PlanTable'
import { ANSWERS_TOAST } from './QuestionList'

let calls: { call: string; body: unknown }[] = []
let refuse: Response | null = null
let toasts: readonly ToastMessage[] = []
let unsubscribe: () => void

/** Start the sample service in one of its filing states. */
function useSample(sample: string) {
  window.history.replaceState(null, '', `/?filingSample=${sample}#/feed?filing=waiting`)
  resetMockState()
}

beforeEach(() => {
  resetFilingState()
  // These tests are about an install where filing is set up.
  setFilingConfigured(true)
  clearResourceCache()
  clearFeedCache()
  calls = []
  refuse = null
  setFetchForTesting(async (url, init) => {
    const path = new URL(url, 'http://x').pathname.replace('/api/radar', '')
    calls.push({ call: `${(init?.method ?? 'GET').toUpperCase()} ${path}`, body: init?.body ? JSON.parse(String(init.body)) : null })
    if (refuse && path.startsWith('/filing/')) return refuse
    return mockFetch(url, init)
  })
  unsubscribe = subscribeToasts((list) => {
    toasts = list
  })
})

afterEach(() => {
  toasts.forEach((entry) => dismissToast(entry.id))
  unsubscribe()
  cleanup()
  setFetchForTesting(null)
  window.history.replaceState(null, '', '/')
})

const posted = (path: string) => calls.filter((entry) => entry.call === `POST ${path}`)

describe('the status line', () => {
  it.each([
    ['auto', /Last run yesterday 21:00: 3 filed, 2 asked/],
    ['stopped', /stopped today 21:00: Obsidian was closed. Next try/],
    ['off', /Background filing is off: items wait until you click File now/],
    ['running', /Filing is running now/],
    ['empty', /quiet for 10 minutes/],
  ])('says what happened in the %s state', async (sample, line) => {
    useSample(sample)
    render(<FeedPage params={{ filing: 'waiting' }} />)
    expect(await screen.findByText(line)).toHaveAttribute('role', 'status')
  })
})

describe('questions', () => {
  it('lists one line per item and sends every answered line with ONE Submit', async () => {
    useSample('auto')
    render(<FeedPage params={{ filing: 'waiting' }} />)
    const groups = await screen.findAllByRole('radiogroup')
    expect(groups).toHaveLength(2)
    expect(screen.getAllByText('Link this to a project?')).toHaveLength(2)
    const submit = screen.getByRole('button', { name: 'Submit answers' })
    expect(submit).toBeDisabled()
    fireEvent.click(within(groups[0]).getByLabelText('Imaging AI'))
    fireEvent.click(within(groups[1]).getByLabelText('No project'))
    fireEvent.click(within(groups[1]).getByLabelText('Reading group'))
    expect(screen.getByText('2 of 2 answered.')).toBeInTheDocument()
    fireEvent.click(submit)
    await waitFor(() => expect(toasts.map((entry) => entry.message)).toContain(ANSWERS_TOAST))
    expect(posted('/filing/answers')).toHaveLength(1)
    expect(posted('/filing/answers')[0].body).toEqual({ answers: [{ question_id: 1, choice: 'Imaging AI' }, { question_id: 2, choice: 'Reading group' }] })
    await waitFor(() => expect(screen.queryAllByRole('radiogroup')).toHaveLength(0))
  })

  it('shows the refusal and keeps the choices when the service says no', async () => {
    useSample('auto')
    refuse = new Response(JSON.stringify({ detail: 'Question 1 is no longer open.' }), { status: 422, headers: { 'Content-Type': 'application/json' } })
    render(<FeedPage params={{ filing: 'waiting' }} />)
    const groups = await screen.findAllByRole('radiogroup')
    fireEvent.click(within(groups[0]).getByLabelText('Imaging AI'))
    fireEvent.click(screen.getByRole('button', { name: 'Submit answers' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Question 1 is no longer open.')
    expect(within(groups[0]).getByLabelText('Imaging AI')).toBeChecked()
  })
})

describe('the plan', () => {
  it('shows one table, strikes a row, and sends ONE Approve with kept and struck rows', async () => {
    useSample('plan')
    render(<FeedPage params={{ filing: 'waiting' }} />)
    const table = await screen.findByRole('table')
    expect(within(table).getAllByRole('row')).toHaveLength(4)
    expect(within(table).getByText('Imaging AI')).toBeInTheDocument()
    expect(within(table).getByText(/Two folders fit/)).toBeInTheDocument()
    const strikes = within(table).getAllByRole('button', { name: /^Strike / })
    fireEvent.click(strikes[2])
    expect(within(table).getAllByRole('button', { name: /^Keep / })).toHaveLength(1)
    expect(screen.getByText(/2 to file, 1 struck/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
    await waitFor(() => expect(toasts.map((entry) => entry.message)).toContain(APPROVED_TOAST))
    expect(posted('/filing/plan/approve')[0].body).toEqual({ approved: [11, 12], struck: [13] })
    await waitFor(() => expect(within(screen.getByRole('table')).getAllByText('Approved')).toHaveLength(2))
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
  })
})

describe('filed recently', () => {
  it('lists the notes, marks best guesses, and opens a note in Obsidian', async () => {
    useSample('auto')
    render(<FeedPage params={{ filing: 'waiting' }} />)
    const heading = await screen.findByRole('heading', { name: 'Filed recently' })
    expect(heading).toBeInTheDocument()
    expect(screen.getAllByText(/placed by best guess/)).toHaveLength(2)
    const open = screen.getAllByRole('button', { name: /in Obsidian$/ })
    fireEvent.click(open[0])
    await waitFor(() => expect(calls.some((entry) => /^POST \/filing\/recent\/\d+\/open$/.test(entry.call))).toBe(true))
  })

  it('shows nothing when nothing was filed', async () => {
    useSample('empty')
    render(<FeedPage params={{ filing: 'waiting' }} />)
    await screen.findByText(/quiet for 10 minutes/)
    expect(screen.queryByRole('heading', { name: 'Filed recently' })).not.toBeInTheDocument()
  })
})

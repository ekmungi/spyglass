// Tests for the How to page: the task data is well-formed, every target parses in the router,
// search filters, a deep link opens its task, Take me there navigates, and the rail has Help.
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { HelpPage, NOT_SET_UP } from '../pages/HelpPage'
import { resetFilingConfigured, setFilingConfigured } from '../state/filingConfigured'
import { buildHash, parseHash, currentRoute } from '../router'
import { Rail } from '../shell/Rail'
import { filterGroups, findTask, HELP_TASKS, splitStep } from './tasks'

beforeEach(() => {
  window.history.replaceState(null, '', '/#/help')
  resetFilingConfigured()
})

afterEach(() => resetFilingConfigured())

describe('task data', () => {
  it('has unique, address-safe ids', () => {
    const ids = HELP_TASKS.map((task) => task.id)
    expect(new Set(ids).size).toBe(ids.length)
    for (const id of ids) expect(parseHash(`#/help/${id}`)).toEqual({ name: 'help', task: id })
  })

  it('gives every task a purpose, steps, a mechanism sentence and balanced step marks', () => {
    for (const task of HELP_TASKS) {
      expect(task.purpose.length, task.id).toBeGreaterThan(10)
      expect(task.steps.length, task.id).toBeGreaterThan(0)
      expect(task.next.length, task.id).toBeGreaterThan(10)
      for (const step of task.steps) expect(step.split('{{').length, `${task.id}: ${step}`).toBe(step.split('}}').length)
    }
  })

  it('has a Take me there target that survives a round trip through the router', () => {
    for (const task of HELP_TASKS) expect(parseHash(buildHash(task.target)), task.id).toEqual(task.target)
  })

  it('splits a step into plain and marked pieces', () => {
    expect(splitStep('Press {{Add feed}} now')).toEqual([
      { text: 'Press ', ui: false },
      { text: 'Add feed', ui: true },
      { text: ' now', ui: false },
    ])
  })

  it('finds a task by id and returns undefined for an unknown id', () => {
    expect(findTask('add-a-feed')?.title).toBe('Add a feed')
    expect(findTask('nope')).toBeUndefined()
    expect(findTask(undefined)).toBeUndefined()
  })
})

describe('router', () => {
  it('parses the help route with and without a task and rejects a malformed one', () => {
    expect(parseHash('#/help')).toEqual({ name: 'help' })
    expect(parseHash('#/help/add-a-feed')).toEqual({ name: 'help', task: 'add-a-feed' })
    expect(parseHash('#/help/Bad Id')).toEqual({ name: 'notfound' })
    expect(buildHash({ name: 'help', task: 'add-a-feed' })).toBe('#/help/add-a-feed')
  })
})

describe('filterGroups', () => {
  it('returns every group for an empty query and drops groups with no match', () => {
    expect(filterGroups('').length).toBeGreaterThan(5)
    const groups = filterGroups('raindrop')
    expect(groups).toHaveLength(1)
    expect(groups[0].tasks[0].id).toBe('set-up-raindrop-slack-mail')
    expect(filterGroups('zzzzqqq')).toHaveLength(0)
  })
})

describe('opening an item', () => {
  it('explains the first-open wait under Reading', () => {
    expect(findTask('open-an-item')?.title).toBe('Open an item in the reader')
    const reading = filterGroups('slow').find((group) => group.id === 'reading')
    expect(reading?.tasks.map((task) => task.id)).toContain('open-an-item')
    const order = filterGroups('').find((group) => group.id === 'reading')?.tasks.map((task) => task.id) ?? []
    expect(order.indexOf('open-an-item')).toBe(order.indexOf('read-todays-brief') + 1)
  })
})

describe('steps in the reader', () => {
  const steps = (id: string) => findTask(id)?.steps.join(' ') ?? ''

  it('name the controls of the reader bar as they are now', () => {
    // Width, thumbs and the chat icon are buttons in the bar; Follow moved into More.
    expect(steps('reading-width-and-font')).toContain('{{Narrower text}} or {{Wider text}}')
    expect(steps('reading-width-and-font')).not.toContain('{{More actions}}')
    expect(steps('more-or-less-like-this')).toContain('{{More like this}} or {{Less like this}}')
    expect(steps('more-or-less-like-this')).not.toContain('{{More actions}}')
    expect(steps('follow-from-an-article')).toContain('{{More}} and choose {{Follow topics from this article}}')
    expect(steps('follow-from-an-article')).not.toContain('{{Follow}}')
    expect(steps('ask-about-an-article')).toContain('{{Ask the assistant about this story}}')
  })
})

describe('steps on the rebuilt pages', () => {
  const steps = (id: string) => findTask(id)?.steps.join(' ') ?? ''

  it('name the Feed as two rows of tabs, one Filters menu and a chat icon, with no search by meaning', () => {
    const feed = steps('use-the-feed-filters')
    expect(feed).toContain('{{Everything}}, {{Missed}}, {{Saved}}, {{From you}} or {{To file}} (shown only when filing is set up)')
    expect(feed).toContain('{{All sections}}')
    expect(feed).toContain('{{Filters}}')
    expect(feed).toContain('{{Show filtered-out items}}')
    expect(feed).not.toMatch(/chip|Related|by meaning/)
    expect(steps('save-for-later')).toContain('{{Saved}} tab')
    expect(steps('save-for-later')).not.toContain('chip')
    expect(steps('file-now-and-approve-the-plan')).toContain('{{To file}} tab')
    expect(steps('file-now-and-approve-the-plan')).not.toContain('chip')
    expect(steps('ask-your-feed')).toContain('{{Ask your feed (opens the assistant)}}')
  })

  it('open the tab of Settings that holds each part before naming the part', () => {
    expect(steps('install-the-browser-extension')).toContain('{{Bringing things in}} tab')
    expect(steps('reading-width-and-font')).toContain('{{Appearance}} tab')
    expect(steps('reading-width-and-font')).toContain('{{Reading font}}')
    expect(steps('choose-engine-and-model')).toContain('{{AI engines}} tab')
    expect(steps('choose-engine-and-model')).toContain('{{Privacy and usage}} tab')
    const settings = steps('privacy-brief-time-and-appearance')
    for (const tab of ['{{Privacy and usage}} tab', '{{General}} tab', '{{Appearance}} tab']) expect(settings).toContain(tab)
  })

  it('open the tab of Profile that holds each part, and save the projects with the one Save profile', () => {
    const profile = steps('edit-your-profile')
    expect(profile).toContain('{{Save profile}}')
    expect(profile).toContain('{{Your projects}} tab')
    expect(profile).not.toContain('{{Save projects}}')
    expect(profile).toContain('saves the project lines too')
  })

  it('open the tab of Sources that holds each group, and name the folded working feeds', () => {
    for (const id of ['add-a-feed', 'pause-or-remove-a-feed', 'check-a-feed-delivers']) expect(steps(id), id).toContain('{{Feeds}} tab')
    expect(steps('pause-or-remove-a-feed')).toContain('{{Show the working feeds}}')
    expect(steps('check-a-feed-delivers')).toContain('{{Show the working feeds}}')
    expect(steps('follow-fda-decisions')).toContain('{{FDA decisions}} tab')
    expect(steps('set-up-raindrop-slack-mail')).toContain('{{From you}} tab')
  })
})

describe('tasks that need filing', () => {
  const FILING_TASKS = ['file-in-vault', 'file-now-and-approve-the-plan']

  it('are flagged, and left out of the groups unless filing is set up', () => {
    for (const id of FILING_TASKS) expect(findTask(id)?.needs, id).toBe('filing')
    const ids = (on: boolean) => filterGroups('', on).flatMap((group) => group.tasks.map((task) => task.id))
    for (const id of FILING_TASKS) {
      expect(ids(false)).not.toContain(id)
      expect(ids(true)).toContain(id)
    }
    expect(filterGroups('vault').flatMap((group) => group.tasks.map((task) => task.id))).not.toContain('file-in-vault')
  })

  it('covers only File now: no plan table and no questions', () => {
    const text = [findTask('file-now-and-approve-the-plan')?.title, ...(findTask('file-now-and-approve-the-plan')?.steps ?? [])].join(' ')
    expect(text).not.toMatch(/plan|question/i)
    expect(text).toContain('File now')
  })

  it('are omitted from the page, and a deep link says the function is not set up', () => {
    setFilingConfigured(false)
    render(<HelpPage task="file-in-vault" />)
    expect(screen.getByText(NOT_SET_UP)).toBeInTheDocument()
    expect(NOT_SET_UP).toBe('This function is not set up on this Spyglass.')
    expect(screen.queryByText('File in vault, and File as')).not.toBeInTheDocument()
    expect(screen.queryByText('File now')).not.toBeInTheDocument()
    expect(screen.getByText('Add a feed')).toBeInTheDocument()
  })

  it('appear, and a deep link opens one, where filing is set up', () => {
    setFilingConfigured(true)
    render(<HelpPage task="file-in-vault" />)
    expect(screen.queryByText(NOT_SET_UP)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /File in vault, and File as/, expanded: true })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^File now/ })).toBeInTheDocument()
  })

  it('leaves the To file chip in the Feed task worded as shown only when filing is set up', () => {
    expect(findTask('use-the-feed-filters')?.steps.join(' ')).toContain('{{To file}} (shown only when filing is set up)')
  })
})

describe('HelpPage', () => {
  it('filters tasks as you type and shows an empty message when nothing matches', () => {
    render(<HelpPage />)
    expect(screen.getByRole('heading', { name: 'How to', level: 1 })).toBeInTheDocument()
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'fda' } })
    expect(screen.getByText('Follow FDA decisions by product code or keyword')).toBeInTheDocument()
    expect(screen.queryByText('Add a feed')).not.toBeInTheDocument()
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'zzzzqqq' } })
    expect(screen.getByText('No task matches that')).toBeInTheDocument()
  })

  it('opens the task named in the address and shows steps and the mechanism', () => {
    render(<HelpPage task="add-a-feed" />)
    expect(screen.getByRole('button', { name: /Add a feed/, expanded: true })).toBeInTheDocument()
    expect(screen.getByText('Add feed')).toHaveClass('rh-ui')
    expect(screen.getByText(/What Spyglass does next/)).toBeInTheDocument()
  })

  it('opens a task on click and Take me there navigates to its screen', () => {
    render(<HelpPage />)
    fireEvent.click(screen.getByRole('button', { name: /Follow a paper search/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Take me there' }))
    expect(currentRoute()).toEqual({ name: 'watch' })
  })

  it('takes the Saved task to the Feed with the Saved filter on', () => {
    render(<HelpPage task="save-for-later" />)
    fireEvent.click(screen.getByRole('button', { name: 'Take me there' }))
    expect(currentRoute()).toEqual({ name: 'feed', params: { saved: 'true' } })
  })
})

describe('rail', () => {
  it('has a Help entry that links to the help route', () => {
    render(<Rail active="today" />)
    expect(screen.getByRole('link', { name: 'Help' })).toHaveAttribute('href', '#/help')
  })
})

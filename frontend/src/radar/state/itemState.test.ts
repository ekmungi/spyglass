// Tests for the optimistic item state: save and vote apply at once, persist on success, and roll
// back with an error toast on failure.
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ItemState } from '../api/types'
import { subscribeToasts } from '../ui/toastStore'
import { effectiveState, markOpened, resetItemState, setVote, toggleSave, type ItemActionsApi } from './itemState'

const BASE: ItemState = { saved: false, opened: false, vote: null, from_user: false, captured_via: null, vault_path: null }

/** An API whose calls resolve or reject as asked, recording what was called. */
function fakeApi(fail = false) {
  const calls: string[] = []
  const settle = (name: string) => {
    calls.push(name)
    return fail ? Promise.reject(new Error('Server unavailable')) : Promise.resolve(null)
  }
  const api: ItemActionsApi = {
    save: (id) => settle(`save:${id}`),
    unsave: (id) => settle(`unsave:${id}`),
    vote: (id, vote) => settle(`vote:${id}:${vote}`),
  }
  return { api, calls }
}

afterEach(() => resetItemState())

describe('toggleSave', () => {
  it('saves optimistically and keeps the change on success', async () => {
    const { api, calls } = fakeApi()
    const pending = toggleSave(1, BASE, api)
    expect(effectiveState(1, BASE).saved).toBe(true) // visible before the request settles
    await expect(pending).resolves.toBe(true)
    expect(effectiveState(1, BASE).saved).toBe(true)
    expect(calls).toEqual(['save:1'])
  })

  it('rolls back and shows an error toast with Retry when the request fails', async () => {
    const { api } = fakeApi(true)
    const toasts = vi.fn()
    const unsubscribe = subscribeToasts(toasts)
    const pending = toggleSave(2, BASE, api)
    expect(effectiveState(2, BASE).saved).toBe(true)
    await expect(pending).resolves.toBe(false)
    expect(effectiveState(2, BASE).saved).toBe(false)
    const last = toasts.mock.calls.at(-1)?.[0] as { message: string; tone: string; action?: { label: string } }[]
    expect(last.at(-1)?.tone).toBe('error')
    expect(last.at(-1)?.message).toMatch(/Could not save/)
    expect(last.at(-1)?.action?.label).toBe('Retry')
    unsubscribe()
  })

  it('unsaves an item the server reported as saved, and restores it on failure', async () => {
    const saved = { ...BASE, saved: true }
    const { api, calls } = fakeApi(true)
    await toggleSave(3, saved, api)
    expect(calls).toEqual(['unsave:3'])
    expect(effectiveState(3, saved).saved).toBe(true)
  })

  it('restores the earlier local change, not the server copy, after a failure', async () => {
    await toggleSave(4, BASE, fakeApi().api) // now saved locally
    await toggleSave(4, BASE, fakeApi(true).api) // unsave fails
    expect(effectiveState(4, BASE).saved).toBe(true)
  })
})

describe('setVote', () => {
  it('sets a vote and clears it when chosen again', async () => {
    const { api, calls } = fakeApi()
    await setVote(5, BASE, 'more', api)
    expect(effectiveState(5, BASE).vote).toBe('more')
    await setVote(5, BASE, 'more', api)
    expect(effectiveState(5, BASE).vote).toBeNull()
    expect(calls).toEqual(['vote:5:more', 'vote:5:null'])
  })

  it('rolls back a failed vote', async () => {
    await setVote(6, BASE, 'less', fakeApi(true).api)
    expect(effectiveState(6, BASE).vote).toBeNull()
  })
})

describe('markOpened', () => {
  it('marks an item opened locally', () => {
    markOpened(7)
    expect(effectiveState(7, BASE).opened).toBe(true)
    expect(effectiveState(8, BASE).opened).toBe(false)
  })
})

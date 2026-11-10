import { describe, expect, it } from 'vitest'
import { activeLine, failedLine, folderOf, isActive, usageLine } from './jobs'
import type { ClaudeJob } from './types'

const job = (over: Partial<ClaudeJob>): ClaudeJob => ({
  id: 1, kind: 'prepare-detail', card_id: 5, status: 'running', note_path: null, message: null,
  progress: null, error: null, cost_usd: null, duration_ms: null, num_turns: null,
  created_at: null, started_at: null, finished_at: null, ...over,
})

describe('job wording', () => {
  it('says what a running job is doing', () => {
    expect(activeLine(job({}))).toBe('Preparing the detailed note in the background')
    expect(activeLine(job({ status: 'queued' }))).toBe('Preparing the detailed note: waiting for the job before it')
    expect(activeLine(job({ kind: 'file-note', progress: 'Opening Obsidian' }))).toBe('Filing the note: opening Obsidian')
  })

  it('says why a job failed', () => {
    expect(failedLine(job({ status: 'failed', error: 'Claude stopped: Not logged in' })))
      .toBe("Couldn't prepare the note: Claude stopped: Not logged in")
    expect(failedLine(job({ kind: 'file-note', status: 'failed' }))).toBe("Couldn't file the note: no reason given")
  })

  it('knows active jobs and folders', () => {
    expect(isActive(job({ status: 'queued' }))).toBe(true)
    expect(isActive(job({ status: 'ok' }))).toBe(false)
    expect(isActive(undefined)).toBe(false)
    expect(folderOf('02 AREAS/Imaging/x.md')).toBe('02 AREAS/Imaging')
    expect(folderOf('x.md')).toBe('the vault root')
  })

  it("says when jobs wait for Claude's usage limit, and what a job used", () => {
    const waiting = job({ status: 'queued', progress: "Waiting for Claude's usage limit to reset at 14:00" })
    expect(activeLine(waiting)).toBe("Preparing the detailed note: waiting for Claude's usage limit to reset at 14:00")
    expect(usageLine(job({ status: 'ok', usage_five_hour: 0.5, usage_week: 0.214, model: 'claude-sonnet-5-5' })))
      .toBe('Claude usage after this: 5-hour 50%, week 21% (claude-sonnet-5-5)')
    expect(usageLine(job({ status: 'ok' }))).toBeNull()
  })
})

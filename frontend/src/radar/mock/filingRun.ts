// Sample-mode background filing: the run's status, open questions, a plan and recent filings, so
// the whole To file view can be tried with ?mock=1 and no backend. Pick a state with
// ?mock=1&filingSample=auto|plan|stopped|running|off|empty|unset. Filing counts as set up
// (`status.configured`) in every state but `unset`, which shows the install that has not set it up.
// Without `filingSample` the sample matches this release: background filing is not available
// (`status.background_available` false), so there are no open questions and no plan. The states
// `auto`, `plan` and `running` set `background_available` to true so they can still be previewed.
import type { FilingPlanRow, FilingQuestion, FilingRecent, FilingStatus, FilingSummary, RadarItem } from '../api/types'

export type FilingSample = 'auto' | 'plan' | 'stopped' | 'running' | 'off' | 'empty' | 'unset'
const SAMPLES: FilingSample[] = ['auto', 'plan', 'stopped', 'running', 'off', 'empty', 'unset']
const HOUR = 3600 * 1000

interface RunState {
  sample: FilingSample
  /** Whether this sample state offers background filing. */
  background: boolean
  questions: FilingQuestion[]
  plan: FilingPlanRow[]
  recent: FilingRecent[]
  /** Answers given in sample mode, waiting for the "next run". */
  answered: number
}

let run: RunState | null = null

/** The sample state named in the page address, or auto. */
export function filingSample(search: string = typeof window === 'undefined' ? '' : window.location.search): FilingSample {
  const value = new URLSearchParams(search).get('filingSample')
  return SAMPLES.includes(value as FilingSample) ? (value as FilingSample) : 'auto'
}

/** True when the page address names the sample state (without it the sample matches the release). */
function filingSampleNamed(search: string = typeof window === 'undefined' ? '' : window.location.search): boolean {
  return SAMPLES.includes(new URLSearchParams(search).get('filingSample') as FilingSample)
}

/** Forget the sample run (tests, and a fresh visit to sample mode). */
export function resetFilingRunMock(): void {
  run = null
}

const ago = (hours: number) => new Date(Date.now() - hours * HOUR).toISOString()
const headline = (item: RadarItem | undefined) => item?.headline || item?.title || 'A sample item'

/** Build the fixtures from the sample items the first time they are needed. */
function state(items: RadarItem[]): RunState {
  if (run) return run
  const sample = filingSample()
  const named = filingSampleNamed()
  const background = named && (sample === 'auto' || sample === 'plan' || sample === 'running')
  const [a, b, c, d, e] = items
  const questions: FilingQuestion[] =
    named && sample === 'auto'
      ? [
          { id: 1, item_id: a?.id ?? 1, headline: headline(a), question: 'Link this to a project?', options: ['Imaging AI', 'Reading group', 'No project'], asked_at: ago(14) },
          { id: 2, item_id: b?.id ?? 2, headline: headline(b), question: 'Link this to a project?', options: ['Reading group', 'Side project', 'No project'], asked_at: ago(13) },
        ]
      : []
  const plan: FilingPlanRow[] =
    named && sample === 'plan'
      ? [
          { id: 11, item_id: c?.id ?? 3, headline: headline(c), becomes: 'resource note', place: '03 RESOURCES/Papers/Medicine', name: '20261112_Pathology_Foundation_Model', project: null, unsure: false, reason: '', decision: 'pending', proposed_at: ago(1) },
          { id: 12, item_id: d?.id ?? 4, headline: headline(d), becomes: 'resource note, linked from the project', place: '03 RESOURCES/Papers/Medicine', name: '20261112_Sample_Paper_On_Device_Rules', project: 'Imaging AI', unsure: false, reason: '', decision: 'pending', proposed_at: ago(1) },
          { id: 13, item_id: e?.id ?? 5, headline: headline(e), becomes: 'resource note', place: '03 RESOURCES/Papers/AI', name: '20261112_Sample_Note_On_Agent_Skills', project: null, unsure: true, reason: 'Two folders fit: AI and Medicine.', decision: 'pending', proposed_at: ago(1) },
        ]
      : []
  const recent: FilingRecent[] =
    sample === 'empty' || sample === 'off' || sample === 'unset'
      ? []
      : [
          { item_id: a?.id ?? 1, headline: headline(a), path: '03 RESOURCES/Papers/Medicine/20261111_Sample_Note.md', project: null, best_guess: true, at: ago(14) },
          { item_id: b?.id ?? 2, headline: headline(b), path: '03 RESOURCES/Papers/AI/20261111_Agent_Skills.md', project: null, best_guess: true, at: ago(13) },
          { item_id: d?.id ?? 4, headline: headline(d), path: '03 RESOURCES/Papers/Medicine/20261110_Sample_Paper.md', project: 'Imaging AI', best_guess: false, at: ago(40) },
        ]
  run = { sample, background, questions, plan, recent, answered: 0 }
  return run
}

/** The status the view shows for the sample state. */
function status(current: RunState): FilingStatus {
  const base = { configured: current.sample !== 'unset', background_available: current.background, next_retry: null as string | null, state: 'idle' as const }
  const last = (kind: 'file' | 'plan', result: 'ok' | 'stopped', extra: Partial<FilingStatus['last_run']> = {}) => ({
    kind, started_at: ago(14.1), finished_at: ago(14), result, reason: null, reason_text: null, detail: null,
    filed: kind === 'file' ? 3 : 0, asked: kind === 'file' ? 2 : 0, proposed: kind === 'plan' ? 3 : 0, ...extra,
  })
  switch (current.sample) {
    case 'unset':
      return { ...base, mode: 'off', last_run: null, line: '' }
    case 'off':
      return { ...base, mode: 'off', last_run: null, line: 'Background filing is off: items wait until you click File now.' }
    case 'running':
      return { ...base, mode: 'auto', state: 'running', last_run: last('file', 'ok'), line: 'Filing is running now (started today 21:02).' }
    case 'stopped':
      return { ...base, mode: 'auto', next_retry: ago(-0.5), last_run: last('file', 'stopped', { reason: 'obsidian_unreachable', reason_text: 'Obsidian was closed', filed: 0, asked: 0 }), line: 'The last run stopped today 21:00: Obsidian was closed. Next try today 21:30.' }
    case 'plan':
      return { ...base, mode: 'plan_first', last_run: last('plan', 'ok'), line: 'Last run today 21:00: 3 proposed.' }
    case 'empty':
      return { ...base, mode: 'auto', last_run: null, line: 'Filing runs after the queue has been quiet for 10 minutes, and at 21:00 each day.' }
    default:
      if (!current.background) return { ...base, mode: 'off', last_run: last('file', 'ok', { asked: 0 }), line: 'Last run yesterday 21:00: 3 filed.' }
      return { ...base, mode: 'auto', last_run: last('file', 'ok'), line: 'Last run yesterday 21:00: 3 filed, 2 asked.' }
  }
}

/** The background-run part of GET /filing. */
export function filingRunView(items: RadarItem[]) {
  const current = state(items)
  return { status: status(current), questions: current.questions, plan: current.plan, recent: current.recent }
}

/** POST /filing/answers: every answer valid, or none stored (422). */
export function answerQuestions(items: RadarItem[], answers: { question_id: number; choice: string }[]): { status: number; body: unknown } {
  const current = state(items)
  for (const answer of answers) {
    const question = current.questions.find((entry) => entry.id === answer.question_id)
    if (!question) return { status: 422, body: { detail: `Question ${answer.question_id} is no longer open.` } }
    if (!question.options.includes(answer.choice)) return { status: 422, body: { detail: `The answer to question ${answer.question_id} is not one of the choices.` } }
  }
  const answeredIds = new Set(answers.map((answer) => answer.question_id))
  run = { ...current, questions: current.questions.filter((entry) => !answeredIds.has(entry.id)), answered: current.answered + answers.length }
  return { status: 200, body: { answered: answers.length } }
}

/** POST /filing/plan/approve: approved rows wait for the next run, struck rows leave. */
export function approvePlan(items: RadarItem[], approved: number[], struck: number[]): { status: number; body: unknown; struckItems: number[] } {
  const current = state(items)
  const pending = new Set(current.plan.filter((row) => row.decision === 'pending').map((row) => row.id))
  if (![...approved, ...struck].length) return { status: 422, body: { detail: 'Approve or strike at least one row.' }, struckItems: [] }
  const unknown = [...approved, ...struck].find((id) => !pending.has(id))
  if (unknown !== undefined) return { status: 422, body: { detail: `Plan row ${unknown} is no longer waiting for a decision.` }, struckItems: [] }
  const struckItems = current.plan.filter((row) => struck.includes(row.id)).map((row) => row.item_id)
  const plan = current.plan
    .filter((row) => !struck.includes(row.id))
    .map((row) => (approved.includes(row.id) ? { ...row, decision: 'approved' as const } : row))
  run = { ...current, plan }
  return { status: 200, body: { approved: approved.length, struck: struck.length }, struckItems }
}

/** The brief's one filing line for the sample state, or null. */
export function filingSummaryMock(items: RadarItem[]): FilingSummary | null {
  const current = state(items)
  if (current.sample === 'stopped') return { line: 'Filing has not run since Tuesday: Obsidian was closed.', filed_yesterday: 0, questions: 0, plan: 0 }
  const questions = current.questions.length
  const plan = current.plan.filter((row) => row.decision === 'pending').length
  const filed = current.sample === 'auto' ? 2 : 0
  const parts = [
    filed ? `Filed yesterday: ${filed} items.` : '',
    questions ? `${questions} ${questions === 1 ? 'question is' : 'questions are'} open.` : '',
    plan ? `A filing plan of ${plan} ${plan === 1 ? 'item' : 'items'} waits for your approval.` : '',
  ].filter(Boolean)
  return parts.length ? { line: parts.join(' '), filed_yesterday: filed, questions, plan } : null
}

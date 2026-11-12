// FilingPanel: the top of the Feed's To file view. One status line says what background filing did
// last and will do next; then the open Questions (one Submit for all), the Plan of a plan-first run
// (one Approve), and the heading of the Waiting group, whose rows are the feed list below. File now
// stays as a quiet secondary control. Filed recently follows the list (FiledRecently).
import type { FilingOverview } from '../api/types'
import { SectionHeading } from '../ui'
import { FileNowControl } from './FileNowControl'
import { PlanTable } from './PlanTable'
import { QuestionList } from './QuestionList'
import './filing.css'

export interface FilingPanelProps {
  /** How many items wait (null while not known yet). */
  count: number | null
  overview: FilingOverview | null
  /** A load error to show beside the status line, or null. */
  error?: string | null
  /** Reload the overview after an answer or an approval. */
  onChanged: () => void
}

/** The empty-queue sentence. */
export const NOTHING_WAITING = 'Nothing is waiting to be filed. Choose File in vault on an item to add it here.'

/** The status line, the groups that need the reader, and the Waiting heading. */
export function FilingPanel({ count, overview, error = null, onChanged }: FilingPanelProps) {
  const questions = overview?.questions ?? []
  const plan = overview?.plan ?? []
  const planPending = plan.some((row) => row.decision === 'pending')
  const line = overview?.status?.line
  const waiting = count ?? 0
  return (
    <div className="r-filing">
      <div className="r-filing__status">
        {line && (
          <p className="r-filing__line" role="status">
            {line}
          </p>
        )}
        {error && <p className="r-filing__problem">{error}</p>}
        {waiting > 0 && <FileNowControl />}
      </div>
      {questions.length > 0 && <QuestionList questions={questions} primary={!planPending} onSubmitted={onChanged} />}
      {plan.length > 0 && <PlanTable rows={plan} onApproved={onChanged} />}
      <SectionHeading note={count === null ? undefined : `${waiting} ${waiting === 1 ? 'item' : 'items'}`}>Waiting</SectionHeading>
      {count === 0 && <p className="r-meta r-filing__empty">{NOTHING_WAITING}</p>}
    </div>
  )
}

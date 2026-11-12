// PlanTable: a "show me the plan first" run's proposals as one table. Each pending row can be
// struck; ONE Approve sends the decision: kept rows are filed by the next run, struck rows leave the
// queue. Approved rows wait for that run and can no longer be struck here.
import { useId, useState } from 'react'
import { approveFilingPlan } from '../api/client'
import { errorMessage } from '../api/errors'
import type { FilingPlanRow } from '../api/types'
import { ItemLink } from '../components/ItemLink'
import { loadFilingCount } from '../state/filingState'
import { Button, IconRemove, IconUndo, Pill, SectionHeading, toast, Tooltip } from '../ui'
import { NoteName, NotePath } from './NotePath'

export interface PlanTableProps {
  rows: FilingPlanRow[]
  /** Called after a successful Approve, so the view reloads. */
  onApproved: () => void
}

/** The toast after Approve. */
export const APPROVED_TOAST = 'Plan approved. The next filing run files the kept rows.'

/** The Plan group of the To file view. */
export function PlanTable({ rows, onApproved }: PlanTableProps) {
  const [struck, setStruck] = useState<ReadonlySet<number>>(new Set())
  const [sending, setSending] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const headingId = useId()
  const pending = rows.filter((row) => row.decision === 'pending')
  const kept = pending.filter((row) => !struck.has(row.id))
  const dropped = pending.filter((row) => struck.has(row.id))

  const toggle = (id: number) => {
    const next = new Set(struck)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setStruck(next)
  }

  const approve = async () => {
    setSending(true)
    setProblem(null)
    try {
      await approveFilingPlan(kept.map((row) => row.id), dropped.map((row) => row.id))
      toast(APPROVED_TOAST)
      setStruck(new Set())
      void loadFilingCount()
      onApproved()
    } catch (cause) {
      setProblem(errorMessage(cause))
    } finally {
      setSending(false)
    }
  }

  return (
    <section className="r-filing__group r-appear" aria-labelledby={headingId}>
      <SectionHeading id={headingId} note="Nothing is written until you approve">
        Plan
      </SectionHeading>
      {/* A table when the column has room; each row becomes a compact block when it does not (a
          container query on this wrapper, see filing.css). The explicit roles keep it a table for
          screen readers whichever way it is drawn. */}
      <div className="r-filing__plan-wrap">
        <table className="r-filing__plan" role="table">
          <thead>
            <tr role="row">
              <th scope="col" role="columnheader">
                Item
              </th>
              <th scope="col" role="columnheader">
                Becomes
              </th>
              <th scope="col" role="columnheader">
                Where
              </th>
              <th scope="col" role="columnheader">
                Name
              </th>
              <th scope="col" role="columnheader">
                Project
              </th>
              <th scope="col" role="columnheader">
                <span className="r-sr-only">Decision</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const isStruck = struck.has(row.id)
              return (
                <tr key={row.id} role="row" className={isStruck ? 'is-struck' : undefined}>
                  <td role="cell" className="r-filing__c-item">
                    <ItemLink id={row.item_id} className="r-filing__headline">
                      {row.headline}
                    </ItemLink>
                    {row.unsure && (
                      <span className="r-filing__unsure">
                        <Pill tone="muted">Unsure</Pill> {row.reason}
                      </span>
                    )}
                  </td>
                  <td role="cell" className="r-filing__c-becomes">
                    {row.becomes}
                  </td>
                  <td role="cell" className="r-filing__c-where">
                    <NotePath path={row.place} />
                  </td>
                  <td role="cell" className="r-filing__c-name">
                    <NoteName name={row.name} />
                  </td>
                  <td role="cell" className="r-filing__c-project">
                    {row.project ? <Pill tone="neutral">{row.project}</Pill> : <span className="r-filing__none">No project</span>}
                  </td>
                  <td role="cell" className="r-filing__c-act">
                    {row.decision === 'approved' ? (
                      <span className="r-meta">Approved</span>
                    ) : (
                      <Tooltip label={isStruck ? 'Keep' : 'Strike'}>
                        <Button
                          variant="quiet"
                          size="sm"
                          className="r-filing__strike"
                          icon={isStruck ? <IconUndo size={14} /> : <IconRemove size={14} />}
                          aria-pressed={isStruck}
                          aria-label={`${isStruck ? 'Keep' : 'Strike'} ${row.headline}`}
                          onClick={() => toggle(row.id)}
                        >
                          <span className="r-filing__strike-text">{isStruck ? 'Keep' : 'Strike'}</span>
                        </Button>
                      </Tooltip>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {pending.length > 0 && (
        <div className="r-filing__actions">
          <Button variant="primary" size="sm" disabled={sending} onClick={() => void approve()}>
            {sending ? 'Saving…' : 'Approve'}
          </Button>
          <span className="r-meta">
            {kept.length} to file{dropped.length ? `, ${dropped.length} struck (they leave the queue)` : ''}. The next run files them.
          </span>
        </div>
      )}
      {problem && (
        <p className="r-filing__problem" role="alert">
          {problem}
        </p>
      )}
    </section>
  )
}

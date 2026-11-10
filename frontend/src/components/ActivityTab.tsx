// Activity tab: per-source run history (successes and failures).
import type { RunRow } from '../lib/types'

/** Table of collection/curation runs, newest first; plain message when empty. */
export function ActivityTab({ runs }: { runs: RunRow[] }) {
  if (runs.length === 0) {
    return <p className="text-muted">No runs yet. Trigger a refresh to see activity.</p>
  }
  return (
    <table className="w-full text-left" style={{ fontSize: 'var(--font-size-body)' }}>
      <thead>
        <tr className="border-b border-border text-muted">
          <th className="py-2 pr-4 font-semibold">Source</th>
          <th className="py-2 pr-4 font-semibold">Status</th>
          <th className="py-2 pr-4 font-semibold">Detail</th>
          <th className="py-2 font-semibold">Started</th>
        </tr>
      </thead>
      <tbody>
        {runs.map((run) => (
          <tr key={run.id} className="border-b border-border">
            <td className="py-2 pr-4 text-ink">{run.source}</td>
            <td
              className={`py-2 pr-4 font-semibold ${
                run.status === 'ok' ? 'text-accent2' : 'text-accent'
              }`}
            >
              {run.status}
            </td>
            <td className="py-2 pr-4 text-body">{run.detail}</td>
            <td className="py-2 text-muted">{new Date(run.started_at).toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

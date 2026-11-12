// UsageSection: what the AI used in the last 7 days, by job, and what "from cache" means.
import { loadUsageReport } from '../../api/usage'
import type { UsageTotals } from '../../api/usageTypes'
import { formatCount, formatShare } from '../../assistant/usageText'
import { SectionHeading, Skeleton } from '../../ui'
import { useLoad } from '../sources/useLoad'
import { purposeLabel } from './usageLabels'

const DAYS = 7

/** One table cell for the cached share: "91%", or a dash when nothing was read. */
function share(row: UsageTotals): string {
  return row.cached_share === null ? '–' : formatShare(row.cached_share)
}

/** The "Usage" group of the Settings page (no props). */
export function UsageSection() {
  const report = useLoad((signal) => loadUsageReport(DAYS, signal))
  const data = report.data
  const rows = data?.by_purpose ?? []
  return (
    <section aria-labelledby="settings-usage" className="rst-section">
      <SectionHeading id="settings-usage">Usage</SectionHeading>
      <p className="r-page-meta">
        Each time Spyglass asks an AI model something, it notes how much the model read and wrote. When the beginning of a request is the
        same as a recent one, the provider re-reads it from its cache at a fraction of the cost. The more of what a model reads comes from
        the cache, the less you use.
      </p>
      {report.loading && !data && (
        <div aria-busy="true" aria-label="Loading usage">
          <Skeleton lines={3} />
        </div>
      )}
      {report.error && !data && <p className="r-error-text">Usage could not be loaded: {report.error}</p>}
      {data && rows.length === 0 && <p className="r-page-meta">Nothing used in the last {DAYS} days.</p>}
      {data && rows.length > 0 && (
        <>
          <table className="rst-usage" aria-label={`AI usage in the last ${DAYS} days`}>
            <thead>
              <tr>
                <th scope="col">Job</th>
                <th scope="col">Calls</th>
                <th scope="col">Read (tokens)</th>
                <th scope="col">From cache</th>
                <th scope="col">Written (tokens)</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.purpose}>
                  <th scope="row">{purposeLabel(row.purpose)}</th>
                  <td>{formatCount(row.calls)}</td>
                  <td>{formatCount(row.context_tokens)}</td>
                  <td>{share(row)}</td>
                  <td>{formatCount(row.output_tokens)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th scope="row">All jobs</th>
                <td>{formatCount(data.totals.calls)}</td>
                <td>{formatCount(data.totals.context_tokens)}</td>
                <td>{share(data.totals)}</td>
                <td>{formatCount(data.totals.output_tokens)}</td>
              </tr>
            </tfoot>
          </table>
          {data.totals.unreported_calls > 0 && (
            <p className="r-page-meta">
              {formatCount(data.totals.unreported_calls)} of these calls came from a service that does not report its token counts, so they
              are counted as calls only.
            </p>
          )}
        </>
      )}
    </section>
  )
}

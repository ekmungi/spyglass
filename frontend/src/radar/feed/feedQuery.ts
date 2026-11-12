// feedQuery: turns the Feed route's filter parameters into the API query.
import type { FeedQuery } from '../api/types'

/**
 * Build the API query from the route's filter parameters. `filingOn` is whether filing is set up;
 * without it a `filing=waiting` parameter (an old link) is ignored and the whole Feed is asked for.
 */
export function feedQuery(params: Record<string, string>, filingOn = true): FeedQuery {
  return {
    section: params.section || undefined,
    kind: params.kind || undefined,
    tier: params.tier || undefined,
    saved: params.saved === 'true' || undefined,
    from_user: params.from_user === 'true' || undefined,
    filed: params.filed === 'true' || undefined,
    filing: filingOn && params.filing === 'waiting' ? ('waiting' as const) : undefined,
    missed: params.missed === 'true' || undefined,
    watch_group: params.watch_group || undefined,
    q: params.q || undefined,
  }
}

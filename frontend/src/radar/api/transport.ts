// Transport: chooses between the real same-origin fetch and the sample-data fetch (mock mode).
import { mockFetch } from '../mock'

export const API_BASE = '/api/radar'

/** True when the URL carries ?mock=1 (before or inside the hash) or VITE_RADAR_MOCK is '1'. */
export function isMockMode(): boolean {
  if (import.meta.env.VITE_RADAR_MOCK === '1') return true
  if (typeof window === 'undefined') return false
  const search = new URLSearchParams(window.location.search)
  if (search.get('mock') === '1') return true
  const hashQuery = window.location.hash.split('?')[1] ?? ''
  return new URLSearchParams(hashQuery).get('mock') === '1'
}

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>

let override: FetchLike | null = null

/** Replace the fetch used by the client (tests); pass null to restore the default. */
export function setFetchForTesting(fn: FetchLike | null): void {
  override = fn
}

/** Fetch a path under /api/radar through the active transport. */
export function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const url = `${API_BASE}${path}`
  if (override) return override(url, init)
  if (isMockMode()) return mockFetch(url, init)
  return fetch(url, init)
}

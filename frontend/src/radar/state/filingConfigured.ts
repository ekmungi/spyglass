// Whether filing into a notes vault is set up on this install: the service says so in
// `status.configured` of GET /filing (true only when the reader named their own Claude Code filing
// skills in their local settings). Everything that belongs to filing (the reader's File in vault
// control, the Feed's To file view, the Today line, the assistant's entry, the Settings controls) is
// shown only when this is true. The answer is loaded once and cached; until it arrives, and when it
// cannot be loaded, the feature counts as not set up, so nothing flashes in and out for the common case.
import { useEffect, useSyncExternalStore } from 'react'
import { getFilingOverview } from '../api/client'
import { isMissing } from '../api/errors'
import type { FilingOverview } from '../api/types'

// null until the service has answered; then true or false.
let configured: boolean | null = null
// Whether this version offers background filing (`status.background_available`); a missing field is false.
let background = false
let request: Promise<void> | null = null
// Bumped by every reset, so an answer that arrives after a reset is dropped instead of stored.
let generation = 0
const listeners = new Set<() => void>()

/** Tell every subscribed component the answer changed. */
function emit(): void {
  listeners.forEach((listener) => listener())
}

/** Subscribe to changes of the answer (for useSyncExternalStore). */
function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** Store the answer; a missing field means not set up. */
export function setFilingConfigured(value: boolean | null): void {
  if (configured === value) return
  configured = value
  emit()
}

/** Store whether background filing is available in this version. */
export function setFilingBackgroundAvailable(value: boolean): void {
  if (background === value) return
  background = value
  emit()
}

/** Read the flags from a GET /filing reply and store them (a reply without a field counts as false). */
export function noteFilingOverview(overview: Pick<FilingOverview, 'status'> | null | undefined): void {
  if (!overview) return
  setFilingBackgroundAvailable(overview.status?.background_available === true)
  setFilingConfigured(overview.status?.configured === true)
}

/** Forget the cached answer (tests, and a full reload of data). */
export function resetFilingConfigured(): void {
  generation += 1
  request = null
  setFilingBackgroundAvailable(false)
  setFilingConfigured(null)
}

/**
 * Ask the service once. A second call while the first runs, or after it answered, does nothing, so
 * only one request is made however many components ask. A service without the filing routes counts
 * as not set up; a network failure leaves the answer unknown and lets the next call try again.
 */
export function ensureFilingConfigured(): void {
  if (request || configured !== null) return
  const mine = generation
  request = getFilingOverview()
    .then((overview) => {
      if (mine === generation) noteFilingOverview(overview)
    })
    .catch((error) => {
      if (mine !== generation) return
      if (isMissing(error)) setFilingConfigured(false)
      request = null
    })
}

/** React hook: true when filing is set up, false when it is not, null while that is not yet known. */
export function useFilingConfiguredState(): boolean | null {
  const value = useSyncExternalStore(subscribe, () => configured, () => configured)
  useEffect(() => {
    ensureFilingConfigured()
  }, [])
  return value
}

/** React hook: true only when this version offers background filing (the controls for it are shown then). */
export function useFilingBackgroundAvailable(): boolean {
  return useSyncExternalStore(subscribe, () => background, () => background)
}

/** React hook: true only when filing is known to be set up (not known yet counts as not set up). */
export function useFilingConfigured(): boolean {
  return useFilingConfiguredState() === true
}

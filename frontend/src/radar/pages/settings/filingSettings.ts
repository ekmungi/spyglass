// The Settings "Filing" group's choices and checks, kept apart from the component.
import type { FilingMode } from '../../api/types'

/** The three modes, each with one plain sentence. */
export const FILING_MODES: { value: FilingMode; label: string; sentence: string }[] = [
  { value: 'off', label: 'Off', sentence: 'Only when I click File now.' },
  { value: 'auto', label: 'File first', sentence: 'Spyglass files queued items in the background and may leave one question: link this to a project?' },
  { value: 'plan_first', label: 'Show me the plan first', sentence: 'Spyglass proposes where each item goes; nothing is written until I approve the plan.' },
]

/** Models offered; a model set elsewhere stays selectable. */
export const MODELS = [
  { value: 'sonnet', label: 'Claude Sonnet (recommended)' },
  { value: 'haiku', label: 'Claude Haiku (cheaper, makes more filing mistakes)' },
  { value: 'opus', label: 'Claude Opus' },
]
export const QUIET_MIN = 2
export const QUIET_MAX = 240
const TIME = /^([01]\d|2[0-3]):[0-5]\d$/

export interface FilingValues {
  mode: FilingMode
  quiet: string
  daily: string
  model: string
}

/** Problems with the values, by field. */
export function validateFiling(values: FilingValues): Partial<Record<keyof FilingValues, string>> {
  const errors: Partial<Record<keyof FilingValues, string>> = {}
  const quiet = Number(values.quiet)
  if (!Number.isInteger(quiet) || quiet < QUIET_MIN || quiet > QUIET_MAX) errors.quiet = `Use a whole number of minutes from ${QUIET_MIN} to ${QUIET_MAX}.`
  if (!TIME.test(values.daily)) errors.daily = 'Use a time like 21:00.'
  return errors
}

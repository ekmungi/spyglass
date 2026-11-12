// request: the choices in the "Open in Claude Code" dialog, and the body they become. The preview
// and the open call send the same body, so the reader is shown exactly what is sent.
import type { ClaudeIntent, ClaudeRequest } from '../api/types'

export interface ClaudeChoice {
  intent: ClaudeIntent
  /** The reader's own request, for `intent: "custom"`. */
  custom: string
}

/** The two ways to use Claude Code on one item, with the one line shown under each. Filing is the To file queue. */
export const INTENT_CHOICES: { intent: ClaudeIntent; label: string; hint: string }[] = [
  { intent: 'discuss', label: 'Discuss this item', hint: 'Talk it through first. Nothing is filed unless you ask.' },
  { intent: 'custom', label: 'My own request', hint: 'Tell Claude Code what you want done with it.' },
]

/** The request body for a choice: only the fields that belong to the chosen intent are sent. */
export function buildClaudeRequest(choice: ClaudeChoice): ClaudeRequest {
  if (choice.intent === 'custom') return { intent: 'custom', custom: choice.custom }
  return { intent: 'discuss' }
}

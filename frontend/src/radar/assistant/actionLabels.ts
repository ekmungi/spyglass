// actionLabels: the reader-facing name of each quick action the assistant offers.
import type { AssistAction } from '../api/types'

export const ACTION_LABELS: Record<AssistAction, string> = {
  explain: 'Explain',
  relevance: 'How is this relevant to me?',
  colleagues: 'Draft message for colleagues',
  linkedin: 'Draft LinkedIn post',
  blog: 'Outline a blog post',
  projects: 'Which of my projects could this help?',
  feed_week: 'What matters most this week?',
  feed_themes: 'Which themes run through my feed?',
}

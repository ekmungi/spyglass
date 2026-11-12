// Usage client: the 7-day report for Settings and the figures behind one assistant answer.
import { request } from './client'
import { ApiError } from './errors'
import type { UsageFigures, UsageReport } from './usageTypes'

/** The report for the last `days` days (1 to 180). */
export function loadUsageReport(days = 7, signal?: AbortSignal): Promise<UsageReport> {
  return request<UsageReport>('GET', `/usage?days=${days}`, undefined, signal)
}

const answers = new Map<number, UsageFigures | null>()

/** Forget the remembered figures (tests). */
export function clearMessageUsage(): void {
  answers.clear()
}

/** The figures of one stored answer, or null when none were kept (older answers, engines that report none). */
export async function loadMessageUsage(messageId: number, signal?: AbortSignal): Promise<UsageFigures | null> {
  if (answers.has(messageId)) return answers.get(messageId) ?? null
  try {
    const figures = await request<UsageFigures>('GET', `/usage/messages/${messageId}`, undefined, signal)
    answers.set(messageId, figures)
    return figures
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 404) {
      answers.set(messageId, null)
      return null
    }
    throw cause
  }
}

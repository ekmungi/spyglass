// errorKind: recognises the one assistant failure that has its own calm message, an engine whose
// account has run out of credit, so the panel can offer a way forward instead of a raw error.

/** The calm line shown in place of the provider's own text. */
export const NO_CREDIT_TEXT = "This engine's account has no credit left."

const NO_CREDIT_PATTERN = /no credit|insufficient (credit|fund)|payment required|\b402\b/i

/** True when a failed answer was caused by an engine account with no credit (HTTP 402 or its wording). */
export function isNoCredit(error: string | null | undefined, status?: number | null): boolean {
  if (status === 402) return true
  return typeof error === 'string' && NO_CREDIT_PATTERN.test(error)
}

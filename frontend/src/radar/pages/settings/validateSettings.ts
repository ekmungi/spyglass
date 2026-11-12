// Validation for the Daily brief and Vault groups, in words a reader can act on.

export const MIN_HOURS = 0.25
export const MAX_HOURS = 24

/** Time zone names this browser knows, or an empty list when it cannot tell. */
export function knownZones(): string[] {
  const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] }
  try {
    return intl.supportedValuesOf?.('timeZone') ?? []
  } catch {
    return []
  }
}

export interface BriefValues {
  time: string
  zone: string
  hours: string
}

/** What is wrong with the brief fields, in words; an empty object means they can be saved. */
export function validateBrief(values: BriefValues, zones: readonly string[] = knownZones()): Partial<Record<keyof BriefValues, string>> {
  const errors: Partial<Record<keyof BriefValues, string>> = {}
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(values.time)) errors.time = 'Use a time like 06:30.'
  const zone = values.zone.trim()
  if (zone && zones.length > 0 && !zones.includes(zone)) errors.zone = 'Use a time zone name like Europe/Amsterdam, or leave it empty for this computer.'
  const hours = Number(values.hours)
  if (!values.hours.trim() || !Number.isFinite(hours) || hours < MIN_HOURS || hours > MAX_HOURS) {
    errors.hours = `Enter a number of hours from ${MIN_HOURS} to ${MAX_HOURS}.`
  }
  return errors
}

export interface VaultValues {
  vault: string
}

/** What is wrong with the vault field: Claude Code cannot be opened in a folder that is not named. */
export function validateVault(values: VaultValues): Partial<Record<keyof VaultValues, string>> {
  const errors: Partial<Record<keyof VaultValues, string>> = {}
  if (!values.vault.trim()) errors.vault = 'Enter the folder your vault lives in.'
  return errors
}

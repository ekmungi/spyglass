// Display names for the kinds of watched entity.

const KIND_LABEL: Record<string, string> = {
  company: 'Company',
  lab: 'Lab',
  regulator: 'Regulator',
  person: 'Person',
  publication: 'Publication',
}

/** Capitalised kind for display ("lab" becomes "Lab"); unknown kinds are shown as sent. */
export function kindLabel(kind: string): string {
  return KIND_LABEL[kind] ?? kind
}

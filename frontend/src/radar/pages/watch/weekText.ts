// Plain words for "how much a group or a name brought into the Feed this week".

/** "12 items this week", "1 item this week" or "Nothing new this week"; empty when the count is unknown. */
export function weekText(count: number | null | undefined): string {
  if (count === null || count === undefined) return ''
  if (count <= 0) return 'Nothing new this week'
  return `${count} ${count === 1 ? 'item' : 'items'} this week`
}

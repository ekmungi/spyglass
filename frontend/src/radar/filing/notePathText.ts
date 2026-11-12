// Helpers for showing vault places and note names in narrow columns: a folder path as segments
// (so it wraps only between folders) and a long file name split for truncation in the middle.

/** How many characters of a file name always stay visible at its end (date stamps lead, so the tail tells notes apart). */
export const NAME_TAIL = 14

/** "03 RESOURCES/Papers/Medicine" as its folder names; empty parts dropped. */
export function pathSegments(path: string): string[] {
  return path
    .split(/[\\/]/)
    .map((segment) => segment.trim())
    .filter(Boolean)
}

/** A full note path split into its folders and its file name (the last segment). */
export function splitNotePath(path: string): { folders: string[]; name: string } {
  const segments = pathSegments(path)
  return { folders: segments.slice(0, -1), name: segments.at(-1) ?? '' }
}

/**
 * A file name as a head that may be cut with an ellipsis and a tail that always shows, so a long
 * name reads "20261112_Sample_Pap…Device_Rules.md". Short names keep everything in the head.
 */
export function splitForMiddleTruncation(name: string, tail: number = NAME_TAIL): { head: string; tail: string } {
  if (name.length <= tail * 2) return { head: name, tail: '' }
  return { head: name.slice(0, -tail), tail: name.slice(-tail) }
}

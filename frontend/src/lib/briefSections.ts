// Splits Daily Brief markdown into narrative / References / Also noticed
// so the reader can render the tails as collapsible panels.

// Section headings are matched only at line starts so prose mentioning
// "## References" mid-line can never trigger a split.
const REFERENCES_HEADING = /^## References[ \t]*$/m
const ALSO_NOTICED_HEADING = /^## Also noticed[ \t]*$/m

// A list item line: bulleted (-, *, +) or numbered (1.) — used to count tail entries.
const ITEM_LINE = /^\s*(?:[-*+]|\d+\.)\s+/

export interface BriefSections {
  // Everything before ## References: the lead paragraph + theme sections.
  narrative: string
  // The References section body (heading stripped); null when absent (old format).
  references: string | null
  // The Also noticed section body (heading stripped); null when absent.
  alsoNoticed: string | null
  // Number of item lines in Also noticed, for the collapsed header count.
  alsoCount: number
}

/** Last match of a line-anchored heading — the renderer appends the tails at the END,
 * so the last occurrence is the real section even if an LLM theme reused the name. */
function lastMatch(pattern: RegExp, text: string): RegExpExecArray | null {
  const global = new RegExp(pattern.source, 'gm')
  let match: RegExpExecArray | null = null
  for (let m = global.exec(text); m !== null; m = global.exec(text)) {
    match = m
  }
  return match
}

/** Split brief markdown at the ## References / ## Also noticed headings.
 * Listed-only briefs have no References section but still carry Also noticed —
 * that tail collapses too. Old-format briefs (neither heading) come back whole
 * as narrative, so the reader renders them exactly as before. */
export function splitBrief(markdown: string): BriefSections {
  const refMatch = lastMatch(REFERENCES_HEADING, markdown)
  if (!refMatch) {
    // No References (listed-only brief): Also noticed may still exist as the sole tail.
    const alsoOnly = lastMatch(ALSO_NOTICED_HEADING, markdown)
    if (!alsoOnly) {
      return { narrative: markdown, references: null, alsoNoticed: null, alsoCount: 0 }
    }
    const alsoNoticed = markdown.slice(alsoOnly.index + alsoOnly[0].length).trim()
    return {
      narrative: markdown.slice(0, alsoOnly.index).trimEnd(),
      references: null,
      alsoNoticed,
      alsoCount: alsoNoticed.split('\n').filter((line) => ITEM_LINE.test(line)).length,
    }
  }

  const narrative = markdown.slice(0, refMatch.index).trimEnd()
  const tail = markdown.slice(refMatch.index + refMatch[0].length)

  const alsoMatch = lastMatch(ALSO_NOTICED_HEADING, tail)
  if (!alsoMatch) {
    return { narrative, references: tail.trim(), alsoNoticed: null, alsoCount: 0 }
  }

  const references = tail.slice(0, alsoMatch.index).trim()
  const alsoNoticed = tail.slice(alsoMatch.index + alsoMatch[0].length).trim()
  const alsoCount = alsoNoticed
    .split('\n')
    .filter((line) => ITEM_LINE.test(line)).length
  return { narrative, references, alsoNoticed, alsoCount }
}

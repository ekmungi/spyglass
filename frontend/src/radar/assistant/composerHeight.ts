// composerHeight: how tall the message box may grow before it scrolls: six lines of its own text.

/** Most lines the composer shows before it scrolls. */
export const MAX_LINES = 6

/** The tallest height in px for a text box with this style: six lines plus its vertical padding. */
export function maxComposerHeight(style: Pick<CSSStyleDeclaration, 'lineHeight' | 'fontSize' | 'paddingTop' | 'paddingBottom'>): number {
  const fontSize = parseFloat(style.fontSize) || 15
  // "normal" is not a number; browsers use about 1.4 times the font size for it.
  const lineHeight = parseFloat(style.lineHeight) || fontSize * 1.4
  const padding = (parseFloat(style.paddingTop) || 0) + (parseFloat(style.paddingBottom) || 0)
  return Math.round(lineHeight * MAX_LINES + padding)
}

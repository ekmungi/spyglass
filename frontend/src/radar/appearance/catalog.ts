// Catalog of the appearance choices: reading fonts, interface fonts and text sizes, with the CSS
// font stack for each and (for bundled fonts beyond the defaults) the loader for its latin files.
//
// The default (Fira Sans) and the two classic choices (Newsreader, Inter) are imported statically by styles.css so the first paint
// never waits for a font. Every other family is a separate CSS chunk, fetched only when someone
// selects it (or opens the Appearance settings, which previews each option in its own typeface).

export type ThemeChoice = 'system' | 'light' | 'dark'
export type NotesFontId = 'fira-sans' | 'source-sans-3' | 'nunito-sans'
export type ReadingFontId = 'newsreader' | NotesFontId | 'source-serif-4' | 'literata' | 'lora' | 'crimson-pro' | 'sans'
export type UiFontId = 'inter' | NotesFontId | 'figtree' | 'dm-sans' | 'ibm-plex-sans' | 'geist' | 'system'
export type TextSizeId = 'comfortable' | 'compact' | 'large'

/** Where an option sits in the picker: the default alone, then the reader's own notes theme, then the rest. */
export type FontGroup = 'default' | 'notes' | 'more'

/** The small heading shown above each group in the picker (the default group has none). */
export const FONT_GROUP_LABELS: Record<FontGroup, string | null> = { default: null, notes: 'From your notes theme', more: 'More' }

export interface FontOption<Id extends string> {
  id: Id
  label: string
  group: FontGroup
  /** The CSS font-family list: the family first, then fallbacks that exist on every machine. */
  stack: string
  /** Fetches the family's @font-face CSS; null when it ships in the main bundle or is a system font. */
  load: (() => Promise<unknown>) | null
}

export const SYSTEM_SANS = 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'
const GEORGIA = 'Georgia, "Times New Roman", serif'

const SANS_FALLBACK = '"Segoe UI", system-ui, sans-serif'

/**
 * The default for reading and for the interface. It is imported statically by styles.css so the
 * first paint already uses it; it also heads the reader's own notes-theme families.
 */
const FIRA_SANS = { id: 'fira-sans' as const, label: 'Fira Sans', stack: `"Fira Sans", ${SANS_FALLBACK}`, load: null }

/** The other sans families from the reader's own notes theme; offered for reading and for the interface. */
const NOTES_FONTS: ReadonlyArray<{ id: NotesFontId; label: string; stack: string; load: () => Promise<unknown> }> = [
  { id: 'source-sans-3', label: 'Source Sans 3', stack: `"Source Sans 3 Variable", "Source Sans 3", ${SANS_FALLBACK}`, load: () => import('./fonts/source-sans-3.css') },
  { id: 'nunito-sans', label: 'Nunito Sans', stack: `"Nunito Sans Variable", "Nunito Sans", ${SANS_FALLBACK}`, load: () => import('./fonts/nunito-sans.css') },
]

/** Reading font choices (headlines and article text). "sans" follows the interface font. */
export const READING_FONTS: ReadonlyArray<FontOption<ReadingFontId>> = [
  { ...FIRA_SANS, group: 'default' },
  ...NOTES_FONTS.map((font) => ({ ...font, group: 'notes' as const })),
  { id: 'newsreader', label: 'Newsreader', group: 'more', stack: `"Newsreader Variable", "Newsreader", ${GEORGIA}`, load: null },
  { id: 'source-serif-4', label: 'Source Serif 4', group: 'more', stack: `"Source Serif 4 Variable", "Source Serif 4", ${GEORGIA}`, load: () => import('./fonts/source-serif-4.css') },
  { id: 'literata', label: 'Literata', group: 'more', stack: `"Literata Variable", "Literata", ${GEORGIA}`, load: () => import('./fonts/literata.css') },
  { id: 'lora', label: 'Lora', group: 'more', stack: `"Lora Variable", "Lora", ${GEORGIA}`, load: () => import('./fonts/lora.css') },
  { id: 'crimson-pro', label: 'Crimson Pro', group: 'more', stack: `"Crimson Pro Variable", "Crimson Pro", "Palatino Linotype", ${GEORGIA}`, load: () => import('./fonts/crimson-pro.css') },
  { id: 'sans', label: 'Sans (same as interface)', group: 'more', stack: '', load: null },
]

/** Interface font choices (menus, labels, lists, buttons). */
export const UI_FONTS: ReadonlyArray<FontOption<UiFontId>> = [
  { ...FIRA_SANS, group: 'default' },
  ...NOTES_FONTS.map((font) => ({ ...font, group: 'notes' as const })),
  { id: 'inter', label: 'Inter', group: 'more', stack: `"Inter Variable", "Inter", ${SANS_FALLBACK}`, load: null },
  { id: 'figtree', label: 'Figtree', group: 'more', stack: `"Figtree Variable", "Figtree", ${SANS_FALLBACK}`, load: () => import('./fonts/figtree.css') },
  { id: 'dm-sans', label: 'DM Sans', group: 'more', stack: `"DM Sans Variable", "DM Sans", ${SANS_FALLBACK}`, load: () => import('./fonts/dm-sans.css') },
  { id: 'ibm-plex-sans', label: 'IBM Plex Sans', group: 'more', stack: `"IBM Plex Sans Variable", "IBM Plex Sans", ${SANS_FALLBACK}`, load: () => import('./fonts/ibm-plex-sans.css') },
  { id: 'geist', label: 'Geist', group: 'more', stack: `"Geist Variable", "Geist", ${SANS_FALLBACK}`, load: () => import('./fonts/geist.css') },
  { id: 'system', label: 'System', group: 'more', stack: SYSTEM_SANS, load: null },
]

/**
 * The monospace font for code in the reader and the assistant (--font-mono in tokens.css names it).
 * Its CSS is requested at start-up, but the browser downloads the font file only when a code block
 * is actually on screen, so a page without code pays nothing.
 */
export const MONO_FONT: FontOption<'fira-code'> = {
  id: 'fira-code',
  label: 'Fira Code',
  group: 'default',
  stack: '"Fira Code Variable", "Fira Code", ui-monospace, "Cascadia Code", "SF Mono", Consolas, monospace',
  load: () => import('./fonts/fira-code.css'),
}

export interface TextSizeOption {
  id: TextSizeId
  label: string
  /** Multiplier applied to every size in the type scale (--type-scale). */
  scale: number
}

/** Three text sizes; Comfortable is the designed size. */
export const TEXT_SIZES: ReadonlyArray<TextSizeOption> = [
  { id: 'comfortable', label: 'Comfortable', scale: 1 },
  { id: 'compact', label: 'Compact', scale: 0.92 },
  { id: 'large', label: 'Large', scale: 1.12 },
]

/** Reading fonts that are sans-serif; headlines set in them need a heavier weight than the serifs. */
const SANS_READING: readonly ReadingFontId[] = ['sans', FIRA_SANS.id, ...NOTES_FONTS.map((font) => font.id)]

/** The weight headlines must at least have: 600 for a sans reading font (450-500 looks thin), else none. */
export function headingMinWeight(id: ReadingFontId): number {
  return SANS_READING.includes(id) ? 600 : 0
}

/** Width of the centre column in px (the CSS variable --measure); the reader column adds a little for its padding. */
export const TEXT_WIDTH = { min: 560, max: 1100, step: 20, default: 680, quickStep: 40, readerExtra: 20 } as const

/** Keep a width inside the allowed range and on the slider's grid; anything else is the default. */
export function clampTextWidth(value: unknown): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) return TEXT_WIDTH.default
  const stepped = Math.round((value - TEXT_WIDTH.min) / TEXT_WIDTH.step) * TEXT_WIDTH.step + TEXT_WIDTH.min
  return Math.min(TEXT_WIDTH.max, Math.max(TEXT_WIDTH.min, stepped))
}

/** A plain word for a width, so the number needs no explaining. */
export function textWidthWord(px: number): string {
  if (px < 640) return 'Narrow'
  if (px < 780) return 'Medium'
  if (px < 960) return 'Wide'
  return 'Extra wide'
}

/** "Medium · 680px", the label shown beside the slider. */
export function textWidthLabel(px: number): string {
  return `${textWidthWord(px)} · ${px}px`
}

export interface AppearanceState {
  theme: ThemeChoice
  readingFont: ReadingFontId
  uiFont: UiFontId
  textSize: TextSizeId
  textWidth: number
}

export const DEFAULT_APPEARANCE: AppearanceState = {
  theme: 'system',
  readingFont: 'fira-sans',
  uiFont: 'fira-sans',
  textSize: 'comfortable',
  textWidth: TEXT_WIDTH.default,
}

/** Headline and body line used to show each font in its own typeface. */
export const FONT_SAMPLE = {
  headline: 'Regulators clear the first home-use colonoscopy assistant',
  body: 'The trial covered 1,200 patients, and the tool flagged more early polyps than clinicians working alone.',
}

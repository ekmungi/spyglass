// Theme preset system: 12 palettes x 4 treatments = 48 runtime-switchable presets.
// A preset is pure data; applying it sets CSS variables on the root.

export interface Tokens {
  canvas: string
  card: string
  ink: string
  body: string
  muted: string
  border: string
  accent: string
  accent2: string
}

export interface ThemePreset {
  name: string
  label: string
  dark: boolean
  tokens: Tokens
}

export interface Sizes {
  headline: number
  body: number
  meta: number
  actions: number
  lineHeight: number
}

// User-locked defaults from the design session (size tuner, 2026-06-10).
export const DEFAULT_SIZES: Sizes = {
  headline: 19,
  body: 15,
  meta: 11.5,
  actions: 12.5,
  lineHeight: 1.3,
}

// (name, label, dark, canvas, card, ink, body, muted, border, accent, accent2)
const PALETTES: [string, string, boolean, ...string[]][] = [
  ['anthropic-coral', 'Anthropic coral', false, '#faf9f5', '#ffffff', '#141413', '#3d3d3a', '#8e8b82', '#e6dfd8', '#cc785c', '#e8a55a'],
  ['replicate-orange', 'Replicate orange', false, '#f9f7f3', '#ffffff', '#202020', '#3a3a3a', '#575757', '#e3ded2', '#ea2804', '#ff6a3d'],
  ['clay-ochre', 'Clay ochre', false, '#fffaf0', '#ffffff', '#0a0a0a', '#3d3a35', '#8a857c', '#ebe2d0', '#e8b94a', '#ff6b5a'],
  ['cal-mono', 'Cal monochrome', false, '#ffffff', '#fafafa', '#111111', '#374151', '#9ca3af', '#e5e7eb', '#3b82f6', '#fb923c'],
  ['airbnb-rausch', 'Airbnb rausch', false, '#ffffff', '#ffffff', '#222222', '#3f3f3f', '#6a6a6a', '#dddddd', '#ff385c', '#92174d'],
  ['mint-teal', 'Mint teal', false, '#fbfdfc', '#ffffff', '#0f172a', '#334155', '#94a3b8', '#e2e8f0', '#0d9488', '#10b981'],
  ['notion-blue', 'Notion blue', false, '#ffffff', '#f7f7f5', '#191918', '#37352f', '#9b9a97', '#e9e9e7', '#2383e2', '#d9730d'],
  ['mastercard-warm', 'Mastercard warmth', false, '#f8f1e7', '#ffffff', '#1a1a1a', '#42403c', '#8c887f', '#e8dcc8', '#eb6c1e', '#f7b32b'],
  ['forest-sage', 'Forest sage', false, '#f6f8f4', '#ffffff', '#1c1f1a', '#3a4036', '#85907f', '#dde5d8', '#3e7d52', '#a3b18a'],
  ['indigo-slate', 'Indigo slate', false, '#f6f7f9', '#ffffff', '#16181d', '#3c4250', '#8b93a3', '#e1e5eb', '#4f46e5', '#818cf8'],
  ['warm-dark', 'Warm dark', true, '#181715', '#252320', '#faf9f5', '#a09d96', '#7d7a73', '#3a3733', '#cc785c', '#e8a55a'],
  ['linear-dark', 'Linear dark', true, '#0a0a0c', '#141516', '#f7f8f8', '#8a8f98', '#62666d', '#23252a', '#828fff', '#5e6ad2'],
]

const TREATMENTS = ['classic', 'tinted', 'zine', 'quiet'] as const

/** Mix two hex colors; t is the weight of the second color (0..1). */
export function blend(hexA: string, hexB: string, t: number): string {
  const parse = (hex: string) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16))
  const [a, b] = [parse(hexA), parse(hexB)]
  const mixed = a.map((value, i) => Math.round(value + (b[i] - value) * t))
  return `#${mixed.map((v) => v.toString(16).padStart(2, '0')).join('')}`
}

/** Apply one treatment's token transform to a base palette. */
function treat(tokens: Tokens, treatment: (typeof TREATMENTS)[number], dark: boolean): Tokens {
  switch (treatment) {
    case 'tinted':
      return { ...tokens, card: blend(tokens.card, tokens.accent, dark ? 0.16 : 0.08) }
    case 'zine':
      return { ...tokens, border: tokens.ink }
    case 'quiet':
      return { ...tokens, accent: blend(tokens.accent, tokens.muted, 0.45) }
    default:
      return tokens
  }
}

/** Generate all 48 presets from the palette table. */
export function buildPresets(): ThemePreset[] {
  return PALETTES.flatMap(([name, label, dark, ...colors]) => {
    const [canvas, card, ink, body, muted, border, accent, accent2] = colors
    const base: Tokens = { canvas, card, ink, body, muted, border, accent, accent2 }
    return TREATMENTS.map((treatment) => ({
      name: `${name}-${treatment}`,
      label: `${label} (${treatment})`,
      dark: dark as boolean,
      tokens: treat(base, treatment, dark as boolean),
    }))
  })
}

// Status colors for relevance dots: one pair per theme darkness.
const STATUS_COLORS = {
  light: { ok: '#3e7d52', out: '#b04a3a' },
  dark: { ok: '#7bbf90', out: '#d9806f' },
}

/** Apply a preset at runtime: data-theme attribute plus the color variables.
 * Also derives the tokens the workspace chrome needs beyond the 8-color base:
 * a surface inset (canvas nudged toward ink) and the relevance status colors. */
export function applyPreset(preset: ThemePreset): void {
  const root = document.documentElement
  root.dataset.theme = preset.name
  for (const [key, value] of Object.entries(preset.tokens)) {
    root.style.setProperty(`--color-${key}`, value)
  }
  const { canvas, ink } = preset.tokens
  root.style.setProperty('--color-surface', blend(canvas, ink, preset.dark ? 0.03 : 0.04))
  const status = STATUS_COLORS[preset.dark ? 'dark' : 'light']
  root.style.setProperty('--color-ok', status.ok)
  root.style.setProperty('--color-out', status.out)
}

/** Apply user font sizes as CSS variables (independent of the theme layer). */
export function applySizes(sizes: Sizes): void {
  const root = document.documentElement
  root.style.setProperty('--font-size-headline', `${sizes.headline}px`)
  root.style.setProperty('--font-size-body', `${sizes.body}px`)
  root.style.setProperty('--font-size-meta', `${sizes.meta}px`)
  root.style.setProperty('--font-size-actions', `${sizes.actions}px`)
  root.style.setProperty('--leading-body', `${sizes.lineHeight}`)
}

/** Restore the locked default sizes. */
export function resetSizes(): void {
  applySizes(DEFAULT_SIZES)
}

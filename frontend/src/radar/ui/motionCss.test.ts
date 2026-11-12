// Guards for the motion system that jsdom cannot render, checked in the stylesheet text: only
// compositor-friendly properties and colours are transitioned, durations come from the tokens
// (or stay under the 320ms ceiling), and reduced motion zeroes every duration token.
/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')
const sheets: Record<string, string> = {
  'tokens.css': read('./tokens.css'),
  'base.css': read('./base.css'),
  'primitives.css': read('./primitives.css'),
  'overlays.css': read('./overlays.css'),
  'shell.css': read('../shell/shell.css'),
}

// Properties that animate without layout: the transform family, opacity, and colours (plus the
// focus ring's box-shadow, which only changes colour and spread).
const ALLOWED = new Set(['opacity', 'transform', 'scale', 'translate', 'color', 'background-color', 'border-color', 'box-shadow', 'filter', 'text-decoration-color'])

/** Every `transition:` value in a sheet, comments removed. */
function transitions(css: string): string[] {
  const clean = css.replace(/\/\*[\s\S]*?\*\//g, '')
  return Array.from(clean.matchAll(/(?:^|[\s;{])transition:\s*([^;]+);/g), (match) => match[1].trim())
}

/** The property named by each comma-separated part of a transition value. */
function transitionedProperties(value: string): string[] {
  if (value === 'none') return []
  return value.split(/,(?![^(]*\))/).map((part) => part.trim().split(/\s+/)[0])
}

describe('motion stylesheet guards', () => {
  it('transitions only opacity, transforms and colours', () => {
    for (const [name, css] of Object.entries(sheets)) {
      for (const value of transitions(css)) {
        for (const property of transitionedProperties(value)) {
          expect(ALLOWED.has(property), `${name}: transition of "${property}" in "${value}"`).toBe(true)
        }
      }
    }
  })

  it('times every transition with a token, never a literal over 320ms', () => {
    for (const [name, css] of Object.entries(sheets)) {
      for (const value of transitions(css)) {
        for (const literal of value.match(/\b\d+(?:\.\d+)?m?s\b/g) ?? []) {
          const ms = literal.endsWith('ms') ? Number.parseFloat(literal) : Number.parseFloat(literal) * 1000
          expect(ms, `${name}: "${value}"`).toBeLessThanOrEqual(320)
        }
      }
    }
  })

  it('defines three durations at about 120, 200 and 280ms and a small shift', () => {
    const tokens = sheets['tokens.css']
    expect(tokens).toMatch(/--dur-fast:\s*120ms/)
    expect(tokens).toMatch(/--dur:\s*200ms/)
    expect(tokens).toMatch(/--dur-slow:\s*280ms/)
    expect(tokens).toMatch(/--shift:\s*6px/)
    expect(tokens).toMatch(/--ease-enter:\s*cubic-bezier/)
    expect(tokens).toMatch(/--ease-exit:\s*cubic-bezier/)
  })

  it('zeroes every duration and the shift under reduced motion', () => {
    const block = /@media \(prefers-reduced-motion: reduce\)\s*{\s*:root\s*{([^}]*)}/.exec(sheets['tokens.css'])?.[1] ?? ''
    for (const token of ['--dur-fast', '--dur', '--dur-slow']) expect(block).toMatch(new RegExp(`${token}:\\s*0ms`))
    expect(block).toMatch(/--shift:\s*0px/)
  })

  it('stops the looping skeleton shimmer and page transitions under reduced motion', () => {
    expect(sheets['primitives.css']).toMatch(/prefers-reduced-motion: reduce\)\s*{\s*\.r-skel::after\s*{\s*animation:\s*none/)
    expect(sheets['shell.css']).toMatch(/prefers-reduced-motion: reduce\)\s*{\s*::view-transition-group\(\*\)/)
  })
})

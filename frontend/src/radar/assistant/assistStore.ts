// Assistant UI store: which target the panel talks about, whether it is open (per surface),
// its width, and requests handed over from elsewhere (a quoted selection, a preset to send).
import { useSyncExternalStore } from 'react'
import type { AssistAction } from '../api/types'
import { readStored, writeStored } from '../hooks/useLocalStorage'

/** What the panel talks about: one article, one day's brief, or the whole feed. */
export type AssistTarget = { kind: 'item'; id: number; title: string } | { kind: 'brief'; day: string } | { kind: 'feed' }
export type Surface = 'reader' | 'today' | 'feed'

export interface QueuedSend {
  content: string
  action?: AssistAction
  selection?: string
}

export interface AssistUiState {
  target: AssistTarget | null
  open: Record<Surface, boolean>
  width: number
  quote: string | null
  queued: QueuedSend | null
  /** Bumped whenever something asks the composer to take focus. */
  focusToken: number
}

export const MIN_WIDTH = 320
export const MAX_WIDTH = 640
const OPEN_KEY = 'radar.assist.open'
const WIDTH_KEY = 'radar.assist.width'

/** Below this window width the assistant is an overlay sheet (see shell.css) and starts closed. */
export const OVERLAY_BREAKPOINT = 1000

/** Whether the window is too narrow for the assistant to sit beside the page. */
function isNarrow(): boolean {
  return typeof window !== 'undefined' && window.innerWidth < OVERLAY_BREAKPOINT
}

let state: AssistUiState = {
  target: null,
  // On a narrow window the panel would cover the page, so it starts closed whatever was remembered.
  open: isNarrow() ? { reader: false, today: false, feed: false } : { reader: true, today: false, feed: false, ...readStored<Partial<Record<Surface, boolean>>>(OPEN_KEY, {}) },
  width: readStored<number>(WIDTH_KEY, 380),
  quote: null,
  queued: null,
  focusToken: 0,
}
const listeners = new Set<() => void>()

function set(patch: Partial<AssistUiState>): void {
  state = { ...state, ...patch }
  listeners.forEach((listener) => listener())
}

/** Current snapshot (stable between changes). */
export function getAssistState(): AssistUiState {
  return state
}

/** React hook: the assistant UI state. */
export function useAssistState(): AssistUiState {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener)
      return () => {
        listeners.delete(listener)
      }
    },
    () => state,
    () => state,
  )
}

/** Stable key for a target ("item:12", "brief:2026-11-12"). */
export function targetKey(target: AssistTarget | null): string | null {
  if (!target) return null
  if (target.kind === 'feed') return 'feed'
  return target.kind === 'item' ? `item:${target.id}` : `brief:${target.day}`
}

/** Set what the panel is about; a different target clears any pending quote. */
export function setAssistTarget(target: AssistTarget | null): void {
  if (targetKey(target) === targetKey(state.target)) {
    if (target && state.target && target.kind === 'item' && state.target.kind === 'item' && target.title !== state.target.title) set({ target })
    return
  }
  set({ target, quote: null, queued: null })
}

/** Open or close the panel for one surface (remembered across visits). */
export function setAssistOpen(surface: Surface, open: boolean): void {
  const next = { ...state.open, [surface]: open }
  // A choice made on a narrow window is not remembered: it would otherwise open the sheet on every visit.
  if (!isNarrow()) writeStored(OPEN_KEY, next)
  set({ open: next })
}

// Shrinking the window below the breakpoint closes the panel rather than leaving it over the page.
if (typeof window !== 'undefined') {
  window.addEventListener('resize', () => {
    if (isNarrow() && (state.open.reader || state.open.today || state.open.feed)) set({ open: { reader: false, today: false, feed: false } })
  })
}

/** Set the panel width, clamped to the allowed range, and remember it. */
export function setAssistWidth(width: number): void {
  const clamped = Math.round(Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, width)))
  writeStored(WIDTH_KEY, clamped)
  set({ width: clamped })
}

/** Attach a quoted passage above the composer and focus it. */
export function attachQuote(surface: Surface, text: string): void {
  setAssistOpen(surface, true)
  set({ quote: text, focusToken: state.focusToken + 1 })
}

/** Remove the quoted passage. */
export function clearQuote(): void {
  set({ quote: null })
}

/** Ask the panel to send a message as soon as it is ready (opens it). */
export function queueSend(surface: Surface, send: QueuedSend): void {
  setAssistOpen(surface, true)
  set({ queued: send })
}

/** Hand the queued send to the panel exactly once. */
export function takeQueued(): QueuedSend | null {
  const queued = state.queued
  if (queued) set({ queued: null })
  return queued
}

/** Focus the composer (opening the panel). */
export function focusComposer(surface: Surface): void {
  setAssistOpen(surface, true)
  set({ focusToken: state.focusToken + 1 })
}

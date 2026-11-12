// Selection -> ask: reads the reader's current text selection, places the floating toolbar, and
// turns a toolbar choice into either a quote for the composer or a message to send at once.
import type { QueuedSend } from '../assistant/assistStore'

export const MIN_SELECTION = 3
export const MAX_SELECTION = 2000

export interface SelectionRect {
  top: number
  left: number
  width: number
  height: number
  bottom: number
}

export interface SelectionInfo {
  text: string
  rect: SelectionRect
}

/** Minimal Selection surface used here, so tests can pass a plain object. */
export interface SelectionLike {
  isCollapsed: boolean
  rangeCount: number
  toString(): string
  getRangeAt(index: number): { commonAncestorContainer: Node; getBoundingClientRect(): SelectionRect }
}

/**
 * The selected text and its on-screen box, or null when nothing usable is selected: a collapsed
 * selection, one outside `container`, or fewer than 3 characters. Long selections are cut at
 * 2000 characters with an ellipsis; whitespace is collapsed.
 */
export function getSelectionInfo(selection: SelectionLike | null, container: Node | null): SelectionInfo | null {
  if (!selection || !container || selection.isCollapsed || selection.rangeCount === 0) return null
  const range = selection.getRangeAt(0)
  if (!container.contains(range.commonAncestorContainer)) return null
  const raw = selection.toString().replace(/\s+/g, ' ').trim()
  if (raw.length < MIN_SELECTION) return null
  const text = raw.length > MAX_SELECTION ? `${raw.slice(0, MAX_SELECTION - 1).trimEnd()}…` : raw
  const box = range.getBoundingClientRect()
  return { text, rect: { top: box.top, left: box.left, width: box.width, height: box.height, bottom: box.bottom } }
}

const TOOLBAR_GAP = 12 // clear space between the toolbar and the selected line
const TOOLBAR_HEIGHT = 38
const EDGE = 96 // half the toolbar's width plus a margin, so it never leaves the column

/**
 * Where to put the toolbar inside the scrolling reader layer. `top` is the edge of the toolbar that
 * faces the selection: its bottom edge, a gap above the first selected line, or (when there is no
 * room above, under the sticky top bar) its top edge, a gap below the last line. The stylesheet
 * anchors the toolbar by that edge (`translateY(-100%)` above), so its real height never matters and
 * it cannot overlap the selected text. Coordinates are relative to the layer's content box.
 */
export function toolbarPosition(rect: SelectionRect, layer: { top: number; left: number; width: number }, scrollTop: number): { top: number; left: number; below: boolean } {
  const below = rect.top - layer.top < TOOLBAR_HEIGHT + TOOLBAR_GAP + 56 // keep clear of the sticky top bar
  const top = below ? rect.bottom - layer.top + scrollTop + TOOLBAR_GAP : rect.top - layer.top + scrollTop - TOOLBAR_GAP
  const centre = rect.left - layer.left + rect.width / 2
  const left = Math.min(Math.max(centre, EDGE), Math.max(EDGE, layer.width - EDGE))
  return { top: Math.round(top), left: Math.round(left), below }
}

export type SelectionAction = 'ask' | 'explain' | 'why'

export type SelectionRequest = { kind: 'quote'; text: string } | { kind: 'send'; send: QueuedSend }

/** Turn a toolbar choice into a quote (Ask) or an immediate message (Explain, Why is this so?). */
export function selectionRequest(action: SelectionAction, text: string): SelectionRequest {
  if (action === 'ask') return { kind: 'quote', text }
  if (action === 'explain') return { kind: 'send', send: { content: '', action: 'explain', selection: text } }
  return { kind: 'send', send: { content: 'Why is this so?', selection: text } }
}

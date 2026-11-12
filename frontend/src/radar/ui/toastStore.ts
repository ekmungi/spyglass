// Toast store: a tiny module-level queue of transient messages, subscribed to by ToastViewport.

export interface ToastAction {
  label: string
  onClick: () => void
}

export interface ToastMessage {
  id: number
  message: string
  tone: 'info' | 'error'
  action?: ToastAction
}

export interface ToastOptions {
  tone?: 'info' | 'error'
  action?: ToastAction
  durationMs?: number
}

type Listener = (toasts: readonly ToastMessage[]) => void

const DEFAULT_DURATION_MS = 4200
let toasts: readonly ToastMessage[] = []
let nextId = 1
const listeners = new Set<Listener>()

function emit(): void {
  listeners.forEach((listener) => listener(toasts))
}

/** Remove one toast by id (also called by its timer). */
export function dismissToast(id: number): void {
  toasts = toasts.filter((toast) => toast.id !== id)
  emit()
}

/** Show a transient message; errors stay longer. Returns the toast id. */
export function toast(message: string, options: ToastOptions = {}): number {
  const id = nextId++
  const tone = options.tone ?? 'info'
  toasts = [...toasts.slice(-2), { id, message, tone, action: options.action }]
  emit()
  const duration = options.durationMs ?? (tone === 'error' ? DEFAULT_DURATION_MS * 1.6 : DEFAULT_DURATION_MS)
  setTimeout(() => dismissToast(id), duration)
  return id
}

/** Subscribe to the toast list; returns the unsubscribe function. */
export function subscribeToasts(listener: Listener): () => void {
  listeners.add(listener)
  listener(toasts)
  return () => {
    listeners.delete(listener)
  }
}

/** A toast as the viewport shows it: `leaving` while it plays its exit after being dismissed. */
export interface ShownToast {
  item: ToastMessage
  leaving: boolean
}

/**
 * Merge the queue into what is on screen: kept toasts take the queue's copy, toasts gone from the
 * queue are marked leaving (or dropped when there is no exit to play), new ones are appended in
 * queue order. Pure, so it is safe as a React state updater.
 */
export function reconcileToasts(shown: readonly ShownToast[], queue: readonly ToastMessage[], keepLeaving: boolean): ShownToast[] {
  const byId = new Map(queue.map((item) => [item.id, item]))
  const kept = shown.flatMap((entry): ShownToast[] => {
    const fresh = byId.get(entry.item.id)
    if (fresh) return [{ item: fresh, leaving: false }]
    return keepLeaving ? [{ item: entry.item, leaving: true }] : []
  })
  const present = new Set(kept.map((entry) => entry.item.id))
  const added = queue.filter((item) => !present.has(item.id)).map((item) => ({ item, leaving: false }))
  return [...kept, ...added]
}

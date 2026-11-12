// SaveNote: the saving / saved / failed text beside a Save button.
import type { SaveState } from './useSaveState'

/** The status text shown beside a Save button; reserved height so it never shifts the layout. */
export function SaveNote({ state }: { state: Pick<SaveState, 'status' | 'message'> }) {
  return (
    <span className="rst-note" role="status" aria-live="polite">
      {state.status === 'saving' && <span className="r-meta">Saving…</span>}
      {state.status === 'saved' && <span className="rst-ok">{state.message}</span>}
      {state.status === 'error' && <span className="r-error-text">{state.message}</span>}
    </span>
  )
}

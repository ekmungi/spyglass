// useSaveState: the saving / saved / failed feedback every settings group shows beside its button.
import { useCallback, useState } from 'react'
import { errorMessage } from '../../api/errors'

export type SaveStatus = 'idle' | 'saving' | 'saved' | 'error'

export interface SaveState {
  status: SaveStatus
  message: string | null
  /** Run a save; resolves to its outcome text (default "Saved.") or the failure in words. */
  run: (action: () => Promise<string | void>) => Promise<boolean>
  /** Clear a previous outcome (call when the reader edits again). */
  reset: () => void
}

/** Track one group's save: busy flag, success text, or the plain-language failure. */
export function useSaveState(): SaveState {
  const [state, setState] = useState<{ status: SaveStatus; message: string | null }>({ status: 'idle', message: null })
  const run = useCallback(async (action: () => Promise<string | void>): Promise<boolean> => {
    setState({ status: 'saving', message: null })
    try {
      const note = await action()
      setState({ status: 'saved', message: note || 'Saved.' })
      return true
    } catch (cause) {
      setState({ status: 'error', message: errorMessage(cause) })
      return false
    }
  }, [])
  const reset = useCallback(() => setState({ status: 'idle', message: null }), [])
  return { ...state, run, reset }
}

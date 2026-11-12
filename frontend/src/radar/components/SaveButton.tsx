// SaveButton: the bookmark toggle shown on a row (on hover, or always once saved).
import type { ItemState } from '../api/types'
import { toggleSave, useItemState } from '../state/itemState'
import { IconButton, IconSaved, IconSaveForLater } from '../ui'

/** Toggle "Save for later" for an item; reads and writes the shared optimistic item state. */
export function SaveButton({ id, base, size = 'sm' }: { id: number; base: ItemState; size?: 'sm' | 'md' }) {
  const state = useItemState(id, base)
  return (
    <IconButton
      size={size}
      className={`r-save${state.saved ? ' is-saved' : ''}`}
      label={state.saved ? 'Remove from saved' : 'Save for later'}
      pressed={state.saved}
      icon={state.saved ? <IconSaved size={16} /> : <IconSaveForLater size={16} />}
      onClick={(event) => {
        event.stopPropagation()
        void toggleSave(id, base)
      }}
    />
  )
}

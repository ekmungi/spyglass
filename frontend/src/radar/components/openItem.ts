// openItem: open an item in the reader from code (keyboard Enter), with the same side effects as a click.
import { navigate } from '../router'
import { markOpened } from '../state/itemState'

/** Mark the item opened and go to its reader. */
export function openItem(id: number): void {
  markOpened(id)
  navigate({ name: 'item', id })
}

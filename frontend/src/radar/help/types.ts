// Types for the How to page: a task, its steps and its group. The content lives in tasks*.ts.
import type { Route } from '../router'

/** One how-to task. Step text marks button and menu names as {{Name}}, shown in a distinct style. */
export interface HelpTask {
  /** Stable id, also used in the address (#/help/add-a-feed). Lowercase words joined by hyphens. */
  id: string
  title: string
  /** One sentence on what the task is for. */
  purpose: string
  /** Numbered steps naming buttons and menus exactly as the screen does. */
  steps: string[]
  /** One sentence on what Spyglass does next, stated as a mechanism. */
  next: string
  /** The screen (and state, where the router allows) the "Take me there" button opens. */
  target: Route
  /** Extra words the search also matches. */
  keywords?: string[]
  /**
   * The feature this task needs. A task that needs filing is left out of the page, and its address
   * says it is not set up, unless filing into a notes vault is set up on this Spyglass.
   */
  needs?: 'filing'
}

/** A plain heading with the tasks under it. */
export interface HelpGroup {
  id: string
  heading: string
  tasks: HelpTask[]
}

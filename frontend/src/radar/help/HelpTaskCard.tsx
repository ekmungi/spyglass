// HelpTaskCard: one how-to task as a compact row that opens in place and shows its purpose,
// numbered steps, what Spyglass does next, and a "Take me there" button.
import { navigate } from '../router'
import { Button, IconExpand } from '../ui'
import { splitStep } from './tasks'
import type { HelpTask } from './types'

/** One step with its button and menu names set in the distinct style. */
function Step({ text }: { text: string }) {
  return (
    <li>
      {splitStep(text).map((part, index) => (part.ui ? <span key={index} className="rh-ui">{part.text}</span> : <span key={index}>{part.text}</span>))}
    </li>
  )
}

/** The card; `open` and `onToggle` are owned by the page so a deep link can open one. */
export function HelpTaskCard({ task, open, onToggle }: { task: HelpTask; open: boolean; onToggle: () => void }) {
  return (
    <li className="rh-task" id={`help-${task.id}`} data-open={open ? 'true' : 'false'}>
      <button type="button" className="rh-task__head" aria-expanded={open} aria-controls={`help-body-${task.id}`} onClick={onToggle}>
        <span className="rh-task__title">{task.title}</span>
        <IconExpand size={16} className="rh-task__chev" />
      </button>
      {open && (
        <div className="rh-task__body" id={`help-body-${task.id}`}>
          <p>{task.purpose}</p>
          <ol className="rh-steps">
            {task.steps.map((step) => (
              <Step key={step} text={step} />
            ))}
          </ol>
          <p className="rh-next">
            <strong>What Spyglass does next. </strong>
            {task.next}
          </p>
          <Button variant="secondary" size="sm" onClick={() => navigate(task.target)}>
            Take me there
          </Button>
        </div>
      )}
    </li>
  )
}

// MessageView: one turn in the assistant thread. User turns are right-aligned bubbles; answers
// are rendered markdown in the serif, with a caret while streaming and Copy / Retry beneath.
import type { AssistAction } from '../api/types'
import { stripMarkdown } from '../lib/format'
import { navigate } from '../router'
import { Button, toast } from '../ui'
import { ACTION_LABELS } from './actionLabels'
import { AnswerMarkdown } from './answerMarkdown'
import { citedIds } from './citations'
import { isNoCredit, NO_CREDIT_TEXT } from './errorKind'
import { UsageLine } from './UsageLine'
import type { UiMessage } from './useThread'

const DRAFT_ACTIONS: AssistAction[] = ['colleagues', 'linkedin', 'blog']

/** Copy text to the clipboard and confirm (or explain the failure) with a toast. */
function copy(text: string, what: string): void {
  if (!navigator.clipboard) {
    toast('Copying is not available in this browser.', { tone: 'error' })
    return
  }
  navigator.clipboard.writeText(text).then(
    () => toast(`${what} copied`),
    () => toast('Could not copy to the clipboard.', { tone: 'error' }),
  )
}

/** What an answer in the conversation about the feed needs: names for its citations and the Feed filter. */
export interface FeedCitations {
  /** The headline of an item, or null when it is not known (the marker then reads "#id"). */
  label: (id: number) => string | null
  /** The items this conversation was shown; an answer's citations are checked against them. */
  shown: ReadonlySet<number>
  /** Filter the Feed to these items, in this order. */
  showInFeed: (ids: number[]) => void
}

/**
 * One message; `onRetry` is offered for failed or stopped answers, and `onChooseEngine` (opens the
 * engine drop-down) for an answer that failed because the engine has no credit left.
 */
export function MessageView({
  message,
  onRetry,
  onChooseEngine,
  onFileItem,
  feed,
}: {
  message: UiMessage
  onRetry: (key: string) => void
  onChooseEngine?: () => void
  /** Opens "Open in Claude Code" with "File into a project"; offered under an answer about the reader's projects. */
  onFileItem?: () => void
  /** Present for the conversation about the feed: citations become links, with "Show these in the Feed". */
  feed?: FeedCitations
}) {
  if (message.role === 'user') {
    const text = message.content || (message.action ? ACTION_LABELS[message.action] : '')
    return (
      <div className="r-msg r-msg--user">
        <div className="r-msg__bubble">
          {message.selection && <blockquote className="r-msg__quote">{message.selection}</blockquote>}
          {text && <p>{text}</p>}
        </div>
      </div>
    )
  }

  const streaming = message.status === 'streaming'
  const noCredit = message.status === 'error' && isNoCredit(message.error, message.errorStatus)
  const isDraft = message.action !== null && DRAFT_ACTIONS.includes(message.action)
  // Ids an answer cites that the assistant was not shown are not trusted as items.
  const cited = feed && message.status === 'done' ? citedIds(message.content).filter((id) => feed.shown.size === 0 || feed.shown.has(id)) : []
  return (
    <div className={`r-msg r-msg--answer${streaming ? ' is-streaming' : ''}`}>
      {message.content ? (
        <div className="r-md">
          <AnswerMarkdown citeLabel={feed?.label}>{message.content}</AnswerMarkdown>
        </div>
      ) : (
        streaming && <p className="r-msg__thinking">Thinking</p>
      )}
      {message.status === 'error' && noCredit && (
        <div className="r-msg__nocredit" role="alert">
          <p>{NO_CREDIT_TEXT}</p>
          <div className="r-msg__nocredit-actions">
            {onChooseEngine && (
              <Button variant="quiet" size="sm" onClick={onChooseEngine}>
                Choose another engine
              </Button>
            )}
            <Button variant="quiet" size="sm" onClick={() => navigate({ name: 'settings' })}>
              Open Settings
            </Button>
          </div>
          {message.error && (
            <details className="r-msg__details">
              <summary>Details</summary>
              <p>{message.error}</p>
            </details>
          )}
        </div>
      )}
      {message.status === 'error' && !noCredit && (
        <p className="r-msg__error" role="alert">
          {message.error ?? 'The answer stopped unexpectedly.'}
        </p>
      )}
      {message.status === 'stopped' && <p className="r-msg__note">Stopped.</p>}
      {!streaming && (
        <div className="r-msg__actions">
          {message.content && (
            <Button variant="quiet" size="sm" onClick={() => copy(message.content, 'Answer')}>
              Copy
            </Button>
          )}
          {feed && cited.length > 0 && (
            <Button variant="quiet" size="sm" onClick={() => feed.showInFeed(cited)}>
              Show these in the Feed
            </Button>
          )}
          {message.content && isDraft && (
            <Button variant="quiet" size="sm" onClick={() => copy(stripMarkdown(message.content), 'Plain text')}>
              Copy as plain text
            </Button>
          )}
          {message.content && message.action === 'projects' && message.status !== 'error' && onFileItem && (
            <Button variant="quiet" size="sm" onClick={onFileItem}>
              File this item in vault
            </Button>
          )}
          {(message.status === 'error' || message.status === 'stopped') && message.request && (
            <Button variant="quiet" size="sm" onClick={() => onRetry(message.key)}>
              Retry
            </Button>
          )}
        </div>
      )}
      {message.content && <UsageLine messageId={message.id} finished={message.status === 'done'} />}
    </div>
  )
}

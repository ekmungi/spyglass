// AssistantPanel: the resizable right-hand panel. Header with the engine drop-down, the thread,
// quick actions, and the composer. Works for an item (reader) and for the day's brief (Today).
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import type { AssistAction } from '../api/types'
import { errorMessage } from '../api/errors'
import { lookupFeedHeadline } from '../feed/useFeed'
import { navigate } from '../router'
import { Button, EmptyState, IconButton, IconClosePanel, IconMore, Menu, Select, Skeleton } from '../ui'
import { clearQuote, setAssistOpen, setAssistWidth, takeQueued, useAssistState, type AssistTarget, type Surface } from './assistStore'
import { Composer } from './Composer'
import { engineGroups, encodeChoice, useEngineChoice } from './engineChoice'
import { ACTION_LABELS } from './actionLabels'
import { useFilingConfigured } from '../state/filingConfigured'
import { queueItem } from '../state/filingState'
import { headlineFrom } from './citations'
import { MessageView, type FeedCitations } from './MessageView'
import { useThread } from './useThread'
import './assistant.css'

const QUICK_ACTIONS: AssistAction[] = ['explain', 'relevance', 'colleagues', 'linkedin', 'blog', 'projects']
const FEED_ACTIONS: AssistAction[] = ['feed_week', 'feed_themes']

/** How many quick actions show before the rest go behind "More…". */
export const VISIBLE_ACTIONS = 4

/** The quick actions for a target: the feed has its own two; the projects question is about one article, so Today's brief has no use for it. */
function actionsFor(target: AssistTarget | null): AssistAction[] {
  if (target?.kind === 'feed') return FEED_ACTIONS
  return target?.kind === 'brief' ? QUICK_ACTIONS.filter((action) => action !== 'projects') : QUICK_ACTIONS
}

/** Drag handle on the panel's left edge; arrow keys resize too. */
function ResizeHandle({ width }: { width: number }) {
  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    const startX = event.clientX
    const startWidth = width
    const handle = event.currentTarget
    handle.setPointerCapture(event.pointerId)
    const onMove = (move: PointerEvent) => setAssistWidth(startWidth + (startX - move.clientX))
    const onUp = () => {
      handle.removeEventListener('pointermove', onMove)
      handle.removeEventListener('pointerup', onUp)
    }
    handle.addEventListener('pointermove', onMove)
    handle.addEventListener('pointerup', onUp)
  }
  return (
    <div
      className="r-assist__resize"
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize the assistant panel"
      aria-valuenow={width}
      tabIndex={0}
      onPointerDown={onPointerDown}
      onKeyDown={(event) => {
        if (event.key === 'ArrowLeft') setAssistWidth(width + 24)
        if (event.key === 'ArrowRight') setAssistWidth(width - 24)
      }}
    />
  )
}

/** The panel for a surface; the target (item or brief) comes from the assistant store. */
export function AssistantPanel({ surface }: { surface: Surface }) {
  const ui = useAssistState()
  const target = ui.target
  // "File this item in vault" is offered only where filing is set up.
  const filingOn = useFilingConfigured()
  const engines = useEngineChoice()
  const conversation = useThread(target)
  const threadRef = useRef<HTMLDivElement>(null)
  const engineRef = useRef<HTMLDivElement>(null)
  const noEngine = !engines.loading && !engines.error && engines.choice === null
  const [showAllActions, setShowAllActions] = useState(false)
  const actions = actionsFor(target)
  // Keep the list tidy: four actions, the rest behind "More…".
  const shownActions = showAllActions ? actions : actions.slice(0, VISIBLE_ACTIONS)
  const hiddenActions = actions.length - shownActions.length

  // Keep the newest text in view while an answer streams.
  const last = conversation.messages[conversation.messages.length - 1]
  useEffect(() => {
    const element = threadRef.current
    if (element) element.scrollTop = element.scrollHeight
  }, [conversation.messages.length, last?.content])

  /** Send with the chosen engine; a quoted passage travels with the message and is then cleared. */
  const send = (content: string, action?: AssistAction, selection?: string) => {
    const passage = selection ?? ui.quote ?? undefined
    conversation.send({ content, action, selection: passage, engine: engines.choice?.engine, model: engines.choice?.model ?? undefined })
    if (!selection && ui.quote) clearQuote()
  }

  // Run a send queued by the selection toolbar once the thread and engine are ready.
  const ready = conversation.thread !== null && !conversation.streaming && engines.choice !== null
  useEffect(() => {
    if (!ready || !ui.queued) return
    const queued = takeQueued()
    if (queued) send(queued.content, queued.action, queued.selection)
    // send is recreated each render; the queue itself is the trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, ui.queued])

  /** Retry with the engine chosen now, so switching engine after a failure takes effect. */
  const retry = (key: string) => conversation.retry(key, { engine: engines.choice?.engine, model: engines.choice?.model ?? undefined })

  /** Open the engine drop-down (used by "Choose another engine" after a no-credit failure). */
  const openEngineList = () => {
    const select = engineRef.current?.querySelector('select')
    if (!select) return
    select.focus()
    try {
      select.showPicker?.() // needs the click that called us; browsers without it keep the focus
    } catch {
      /* the picker is optional: focus alone still lets the keyboard open the list */
    }
  }

  const subject = target?.kind === 'brief' ? "today's brief" : target?.kind === 'feed' ? 'your feed' : 'this article'
  const feedCitations: FeedCitations | undefined =
    target?.kind === 'feed'
      ? {
          label: (id) => headlineFrom(conversation.retrieved, id) ?? lookupFeedHeadline(id),
          shown: new Set(conversation.retrieved.map((entry) => entry.id)),
          showInFeed: (ids) => navigate({ name: 'feed', params: { cited: ids.join(',') } }),
        }
      : undefined
  const live = conversation.streaming ? 'The assistant is writing an answer.' : last?.status === 'error' ? 'The answer stopped with an error.' : last?.role === 'assistant' ? 'Answer ready.' : ''

  let body
  if (noEngine) {
    body = (
      <div className="r-assist__empty">
        <EmptyState
          title="No assistant is set up yet"
          body="Choose an AI engine and add its key in Settings. Keys are kept in your system's keychain."
          action={<Button onClick={() => navigate({ name: 'settings' })}>Open Settings</Button>}
        />
      </div>
    )
  } else if (conversation.loadError || engines.error) {
    body = (
      <div className="r-assist__empty">
        <p className="r-error-text">{conversation.loadError ?? errorMessage(engines.error)}</p>
        <Button size="sm" onClick={conversation.loadError ? conversation.reload : engines.reload}>
          Try again
        </Button>
      </div>
    )
  } else if (conversation.loading || engines.loading) {
    body = (
      <div className="r-assist__empty">
        <Skeleton lines={3} />
      </div>
    )
  } else if (!conversation.messages.length) {
    body = (
      <div className="r-assist__intro">
        <p className="r-assist__intro-text">
          {target?.kind === 'feed' ? 'Ask about anything in your feed, or describe what to find. Answers cite the items they use.' : `Ask anything about ${subject}, select a passage to ask about it, or start with one of these.`}
        </p>
        <ul className="r-assist__starters">
          {shownActions.map((action) => (
            <li key={action}>
              <button type="button" onClick={() => send('', action)}>
                {ACTION_LABELS[action]}
              </button>
            </li>
          ))}
          {hiddenActions > 0 && (
            <li>
              <button type="button" onClick={() => setShowAllActions(true)}>
                More…
              </button>
            </li>
          )}
        </ul>
      </div>
    )
  } else {
    const fileItem = filingOn && target?.kind === 'item' ? () => void queueItem(target.id) : undefined
    body = conversation.messages.map((message) => (
      <MessageView key={message.key} message={message} onRetry={retry} onChooseEngine={openEngineList} onFileItem={fileItem} feed={feedCitations} />
    ))
  }

  return (
    <aside className="r-assist" style={{ width: ui.width }} aria-label="Assistant">
      <ResizeHandle width={ui.width} />
      <header className="r-assist__head">
        <div className="r-assist__title">
          <h2>Assistant</h2>
          <p>{target?.kind === 'brief' ? "About today's brief" : target?.kind === 'feed' ? 'About your feed' : 'About this article'}</p>
        </div>
        <Menu
          label="Assistant options"
          items={[{ id: 'new', label: 'New conversation', onSelect: conversation.startNew, disabled: !conversation.messages.length }]}
          trigger={<IconButton label="Assistant options" icon={<IconMore size={18} />} tooltipSide="bottom" />}
        />
        <IconButton label="Close assistant" icon={<IconClosePanel size={18} />} onClick={() => setAssistOpen(surface, false)} tooltipSide="bottom" />
      </header>
      {!noEngine && engines.engines.length > 0 && (
        <div className="r-assist__engine" ref={engineRef}>
          <Select label="Engine" hideLabel value={encodeChoice(engines.choice)} onChange={engines.setChoice} groups={engineGroups(engines.engines)} />
        </div>
      )}
      <div className="r-assist__thread" ref={threadRef}>
        {body}
      </div>
      <p className="r-sr-only" aria-live="polite">
        {live}
      </p>
      {!noEngine && (
        <footer className="r-assist__foot">
          {conversation.messages.length > 0 && (
            <div className="r-assist__chips" role="group" aria-label="Quick actions">
              {shownActions.map((action) => (
                <button key={action} type="button" className="r-chip" disabled={conversation.streaming} onClick={() => send('', action)}>
                  {ACTION_LABELS[action]}
                </button>
              ))}
              {hiddenActions > 0 && (
                <button type="button" className="r-chip" onClick={() => setShowAllActions(true)}>
                  More…
                </button>
              )}
            </div>
          )}
          <Composer
            placeholder={target?.kind === 'feed' ? 'Ask your feed, or describe what to find…' : `Ask about ${subject}`}
            quote={ui.quote}
            onClearQuote={clearQuote}
            streaming={conversation.streaming}
            disabled={conversation.thread === null}
            focusToken={ui.focusToken}
            onSend={(text) => send(text)}
            onStop={conversation.stop}
          />
        </footer>
      )}
    </aside>
  )
}

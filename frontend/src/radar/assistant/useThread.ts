// useThread: the conversation for the panel's current target. Loads (or creates) the thread,
// streams answers with Stop and Retry, and keeps each target's thread in memory between visits.
import { useCallback, useEffect, useRef, useState } from 'react'
import { createThread } from '../api/client'
import { ApiError, errorMessage } from '../api/errors'
import { streamMessage } from '../api/stream'
import type { AssistAction, AssistMessage, RetrievedItem, SendMessageBody, Thread } from '../api/types'
import { targetKey, type AssistTarget } from './assistStore'

export type MessageStatus = 'done' | 'streaming' | 'error' | 'stopped'

export interface UiMessage {
  key: string
  id: number | null
  role: 'user' | 'assistant'
  content: string
  selection: string | null
  action: AssistAction | null
  status: MessageStatus
  error: string | null
  /** HTTP status of the failure when the request itself was refused (for example 402), else undefined. */
  errorStatus?: number
  /** The request that produced an assistant message, kept for Retry. */
  request?: SendMessageBody
}

interface Conversation {
  thread: Thread | null
  messages: UiMessage[]
  /** The items a conversation about the feed has been shown, so its citations can name them. */
  retrieved: RetrievedItem[]
}

/** The earlier list with `added` folded in (a newer headline replaces an older one for the same id). */
export function mergeRetrieved(current: RetrievedItem[], added: RetrievedItem[] | undefined): RetrievedItem[] {
  if (!added?.length) return current
  const ids = new Set(added.map((entry) => entry.id))
  return [...current.filter((entry) => !ids.has(entry.id)), ...added]
}

const conversations = new Map<string, Conversation>()
let localKey = 0
const nextKey = () => `m${++localKey}`

/** Forget every remembered conversation (tests, or after the service restarts). */
export function resetConversations(): void {
  conversations.clear()
}

/** Convert a stored message into the panel's message shape. */
export function fromServer(message: AssistMessage): UiMessage {
  return {
    key: `s${message.id}`,
    id: message.id,
    role: message.role,
    content: message.content,
    selection: message.selection,
    action: message.action,
    status: message.error ? 'error' : 'done',
    error: message.error,
  }
}

/** The request body for creating or fetching the thread of a target. */
function threadBody(target: AssistTarget, fresh: boolean) {
  const base = target.kind === 'item' ? { item_id: target.id } : target.kind === 'brief' ? { brief_day: target.day } : { scope: 'feed' as const }
  return fresh ? { ...base, new: true } : base
}

export interface ThreadApi {
  thread: Thread | null
  messages: UiMessage[]
  /** The items the feed conversation has been shown (empty for other targets). */
  retrieved: RetrievedItem[]
  loading: boolean
  loadError: string | null
  streaming: boolean
  send: (body: SendMessageBody) => void
  stop: () => void
  retry: (key: string, override?: Pick<SendMessageBody, 'engine' | 'model'>) => void
  startNew: () => void
  reload: () => void
}

/** What the panel shows for one target: its conversation plus the state of loading it. */
interface View {
  key: string | null
  conversation: Conversation
  loading: boolean
  loadError: string | null
}

const EMPTY: Conversation = { thread: null, messages: [], retrieved: [] }

/** The view for a target at first sight: its remembered conversation, or an empty one that is loading. */
function viewFor(key: string | null): View {
  const cached = key ? conversations.get(key) : undefined
  if (cached?.thread) return { key, conversation: cached, loading: false, loadError: null }
  return { key, conversation: cached ?? EMPTY, loading: key !== null, loadError: null }
}

/** The conversation for `target`; null target means the panel has nothing to talk about. */
export function useThread(target: AssistTarget | null): ThreadApi {
  const key = targetKey(target)
  const [view, setView] = useState<View>(() => viewFor(key))
  const [nonce, setNonce] = useState(0)
  const abortRef = useRef<AbortController | null>(null)
  const freshRef = useRef(false)

  // A different target starts from that target's remembered conversation (state adjusted during
  // render); this render already reports the new target, so it never shows the previous one's turns.
  let current = view
  if (view.key !== key) {
    current = viewFor(key)
    setView(current)
  }
  const conversation = current.conversation

  /**
   * Update one target's conversation. The cache is the source of truth, so a stream that finishes
   * after the reader moved to another item still lands in its own conversation; the visible state
   * changes only when that target is still the one on screen.
   */
  const update = useCallback((forKey: string, updater: (current: Conversation) => Conversation) => {
    const next = updater(conversations.get(forKey) ?? EMPTY)
    conversations.set(forKey, next)
    setView((previous) => (previous.key === forKey ? { ...previous, conversation: next } : previous))
  }, [])

  useEffect(() => {
    abortRef.current?.abort()
    if (!target || !key) {
      return
    }
    const cached = conversations.get(key)
    if (cached?.thread && !freshRef.current) {
      return
    }
    let cancelled = false
    createThread(threadBody(target, freshRef.current))
      .then((result) => {
        if (cancelled) return
        const next = { thread: result.thread, messages: result.messages.map(fromServer), retrieved: result.retrieved ?? [] }
        conversations.set(key, next)
        setView({ key, conversation: next, loading: false, loadError: null })
      })
      .catch((cause: unknown) => {
        if (!cancelled) setView((previous) => (previous.key === key ? { ...previous, loading: false, loadError: errorMessage(cause) } : previous))
      })
      .finally(() => {
        freshRef.current = false
      })
    return () => {
      cancelled = true
    }
    // target is represented by key; nonce forces a reload.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, nonce])

  useEffect(() => () => abortRef.current?.abort(), [])

  /** Stream an answer into a new assistant message, given the request body. */
  const runStream = useCallback(
    (body: SendMessageBody, threadId: number, forKey: string) => {
      const answerKey = nextKey()
      update(forKey, (current) => ({
        ...current,
        messages: [...current.messages, { key: answerKey, id: null, role: 'assistant', content: '', selection: null, action: body.action ?? null, status: 'streaming', error: null, request: body }],
      }))
      const patch = (changes: Partial<UiMessage>) =>
        update(forKey, (current) => ({ ...current, messages: current.messages.map((message) => (message.key === answerKey ? { ...message, ...changes } : message)) }))
      const controller = new AbortController()
      abortRef.current = controller
      let text = ''
      streamMessage(
        threadId,
        body,
        (event) => {
          if (event.type === 'delta') {
            text += event.text
            patch({ content: text })
          }
          if (event.type === 'done' && event.retrieved) update(forKey, (current) => ({ ...current, retrieved: mergeRetrieved(current.retrieved, event.retrieved) }))
        },
        controller.signal,
      )
        .then((result) => {
          if (result.outcome === 'done') patch({ status: 'done', id: result.messageId, content: result.text })
          else if (result.outcome === 'aborted') patch({ status: 'stopped' })
          else patch({ status: 'error', error: result.error ?? 'The answer stopped unexpectedly.' })
        })
        .catch((cause: unknown) => patch({ status: 'error', error: errorMessage(cause), errorStatus: cause instanceof ApiError ? cause.status : undefined }))
        .finally(() => {
          if (abortRef.current === controller) abortRef.current = null
        })
    },
    [update],
  )

  const threadId = conversation.thread?.id ?? null
  const streaming = conversation.messages.some((message) => message.status === 'streaming')

  const send = useCallback(
    (body: SendMessageBody) => {
      if (threadId === null || streaming || !key) return
      update(key, (current) => ({
        ...current,
        messages: [...current.messages, { key: nextKey(), id: null, role: 'user', content: body.content, selection: body.selection ?? null, action: body.action ?? null, status: 'done', error: null }],
      }))
      runStream(body, threadId, key)
    },
    [threadId, streaming, key, update, runStream],
  )

  const stop = useCallback(() => abortRef.current?.abort(), [])

  const retry = useCallback(
    (messageKey: string, override?: Pick<SendMessageBody, 'engine' | 'model'>) => {
      if (threadId === null || streaming || !key) return
      const failed = conversation.messages.find((message) => message.key === messageKey)
      if (!failed?.request) return
      update(key, (current) => ({ ...current, messages: current.messages.filter((message) => message.key !== messageKey) }))
      // A retry uses the engine chosen now (the reader may have switched after a failure).
      runStream(override?.engine ? { ...failed.request, engine: override.engine, model: override.model } : failed.request, threadId, key)
    },
    [threadId, streaming, key, conversation.messages, update, runStream],
  )

  const startNew = useCallback(() => {
    if (!key) return
    abortRef.current?.abort()
    conversations.delete(key)
    freshRef.current = true
    setView((previous) => ({ ...previous, conversation: EMPTY, loading: true, loadError: null }))
    setNonce((value) => value + 1)
  }, [key])

  const reload = useCallback(() => {
    setView((previous) => ({ ...previous, loading: true, loadError: null }))
    setNonce((value) => value + 1)
  }, [])

  return { thread: conversation.thread, messages: conversation.messages, retrieved: conversation.retrieved, loading: current.loading, loadError: current.loadError, streaming, send, stop, retry, startNew, reload }
}

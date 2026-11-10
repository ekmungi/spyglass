// Application shell: data loading, segmented tab nav, and the six tabs
// (daily brief, research workspace, feeds, activity, archive, settings).
import { Activity, Archive, Columns2, Inbox, Newspaper, Rss, Settings, Telescope } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { ActivityTab } from './components/ActivityTab'
import { ArchivedTab } from './components/ArchivedTab'
import { BriefTab } from './components/BriefTab'
import { CopyPromptButton } from './components/CopyPromptButton'
import { FeedsTab } from './components/FeedsTab'
import { InboxTab } from './components/InboxTab'
import { LinkIndicator } from './components/LinkIndicator'
import { SegmentedControl } from './components/SegmentedControl'
import { SettingsTab } from './components/SettingsTab'
import { ZoomControl } from './components/ZoomControl'
import { WorkspaceView } from './components/workspace/WorkspaceView'
import * as api from './lib/api'
import { applyStoredAppearance } from './lib/appearance'
import { copyText, referenceText } from './lib/link'
import { useLinkStatus } from './lib/useLinkStatus'
import type { CardData, CardPatch, FeedData, RunRow } from './lib/types'
import { applyStoredZoom } from './lib/useZoom'

type Tab = 'brief' | 'inbox' | 'workspace' | 'feeds' | 'activity' | 'archive' | 'settings'

const TABS = [
  // Brief leads: the Daily Brief is the MVP front door.
  { value: 'brief' as Tab, label: 'Brief', icon: <Newspaper size={13} /> },
  // Papers the user shared in Slack, filed with a debrief.
  { value: 'inbox' as Tab, label: 'Inbox', icon: <Inbox size={13} /> },
  { value: 'workspace' as Tab, label: 'Workspace', icon: <Columns2 size={13} /> },
  { value: 'feeds' as Tab, label: 'Feeds', icon: <Rss size={13} /> },
  { value: 'activity' as Tab, label: 'Activity', icon: <Activity size={13} /> },
  { value: 'archive' as Tab, label: 'Archive', icon: <Archive size={13} /> },
  { value: 'settings' as Tab, label: 'Settings', icon: <Settings size={13} /> },
]

/** Cheap equality on the fields that affect rendering, to skip needless re-renders. */
function sameCards(a: CardData[], b: CardData[]): boolean {
  if (a.length !== b.length) {
    return false
  }
  const sig = (c: CardData) =>
    `${c.id}|${c.state}|${c.curated}|${c.category}|${c.relevance}|${c.note}`
  return a.every((card, i) => sig(card) === sig(b[i]))
}

/** Root component: loads data on open and routes between the tabs. */
function App() {
  const [tab, setTab] = useState<Tab>('workspace')
  const [cards, setCards] = useState<CardData[]>([])
  const [archived, setArchived] = useState<CardData[]>([])
  const [runs, setRuns] = useState<RunRow[]>([])
  const [feeds, setFeeds] = useState<FeedData[]>([])
  const [status, setStatus] = useState('loading')
  // The prompt to copy when the Claude desktop app could not be opened.
  const [fallbackPrompt, setFallbackPrompt] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  // A card a brief's card: link asked to open in the reader; consumed once.
  const [openCardRequest, setOpenCardRequest] = useState<number | null>(null)
  // Stable identity: WorkspaceView keys its consume-once effect on this callback, so an
  // inline arrow would re-run that effect on every App render for nothing.
  const onCardRequestHandled = useCallback(() => setOpenCardRequest(null), [])

  const loadCards = useCallback(async () => {
    const fetched = await api.getCards()
    setCards(fetched)
    const uncurated = fetched.filter((c) => !c.curated).length
    const extra = uncurated > 0 ? `, ${uncurated} uncurated` : ''
    setStatus(`${fetched.length} cards${extra}`)
  }, [])

  useEffect(() => {
    // Restore the saved theme, font sizes, layout widths, and zoom before first paint.
    applyStoredAppearance()
    applyStoredZoom()
  }, [])

  useEffect(() => {
    // Run-on-open-if-stale, then show whatever we have (errors stay visible).
    api
      .refresh(true)
      .then(loadCards)
      .catch((error: Error) => setStatus(error.message))
  }, [loadCards])

  useEffect(() => {
    if (tab === 'feeds') {
      api.getFeeds().then(setFeeds).catch((error: Error) => setStatus(error.message))
    }
    if (tab === 'activity') {
      api.getRuns().then(setRuns).catch((error: Error) => setStatus(error.message))
    }
    if (tab === 'archive') {
      api.getCards({ state: 'dismissed' }).then(setArchived).catch((e: Error) => setStatus(e.message))
    }
  }, [tab])

  useEffect(() => {
    // Keep the workspace in sync with changes Claude makes in the background
    // (categorize, relevance, curation) without a manual reload. Re-fetch on a
    // timer AND whenever the dashboard regains focus/visibility -- the focus
    // case is what matters when switching back from the Claude terminal. Only
    // re-render when something actually changed (cheap signature compare).
    if (tab !== 'workspace') {
      return
    }
    const reload = () =>
      api
        .getCards()
        .then((fetched) => setCards((prev) => (sameCards(prev, fetched) ? prev : fetched)))
        .catch(() => {})
    const id = setInterval(reload, 10000)
    const onVisible = () => {
      if (document.visibilityState === 'visible') reload()
    }
    window.addEventListener('focus', reload)
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      clearInterval(id)
      window.removeEventListener('focus', reload)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [tab])

  const forceRefresh = () => {
    setRefreshing(true)
    setStatus('refreshing...')
    api
      .refresh(false)
      .then(loadCards)
      .catch((error: Error) => setStatus(error.message))
      .finally(() => setRefreshing(false))
  }

  const onUpdate = (id: number, patch: CardPatch) => {
    api
      .patchCard(id, patch)
      .then((updated) =>
        setCards((current) => current.map((card) => (card.id === id ? updated : card))),
      )
      .catch((error: Error) => setStatus(error.message))
  }

  const onMerge = (id: number, fields: Partial<CardData>) => {
    // Taxonomy PATCH responses only return the changed fields + override flags.
    setCards((current) =>
      current.map((card) => (card.id === id ? { ...card, ...fields } : card)),
    )
  }

  const onUnarchive = (id: number) => {
    api
      .patchCard(id, { state: 'new' })
      .then(() => {
        setArchived((current) => current.filter((card) => card.id !== id))
        return loadCards()
      })
      .catch((error: Error) => setStatus(error.message))
  }

  const onDelete = (id: number) => {
    api
      .deleteCard(id)
      .then(() => setCards((current) => current.filter((card) => card.id !== id)))
      .catch((error: Error) => setStatus(error.message))
  }

  const onFeedUpdate = (id: number, patch: { enabled?: boolean; name?: string }) => {
    api
      .patchFeed(id, patch)
      .then((updated) =>
        setFeeds((current) => current.map((f) => (f.id === id ? updated : f))),
      )
      .catch((error: Error) => setStatus(error.message))
  }

  const onFeedDelete = (id: number) => {
    api
      .deleteFeed(id)
      .then(() => setFeeds((current) => current.filter((f) => f.id !== id)))
      .catch((error: Error) => setStatus(error.message))
  }

  const onFeedRefresh = () => {
    api.getFeeds().then(setFeeds).catch((error: Error) => setStatus(error.message))
  }

  const onOpenExternal = (id: number) => {
    api.openExternal(id).catch((error: Error) => setStatus(error.message))
  }

  // The linked Claude session: conversations about items go to it.
  const { status: link, watch: watchLink, refresh: refreshLink } = useLinkStatus()

  const claudeFailed = (error: Error) => {
    setStatus(error.message)
    if (error instanceof api.ClaudeUnavailableError) setFallbackPrompt(error.prompt)
  }

  const openLinkedSession = (cardIds?: number[], task?: string) => {
    setFallbackPrompt(null)
    api
      .openLinkedSession(cardIds, task)
      .then(() => {
        setStatus('Opened a linked Claude session: press Enter in Claude desktop to link it')
        watchLink()
      })
      .catch(claudeFailed)
  }

  // A conversation about items. With a session linked, the items are selected and the
  // request is copied to paste there, since nothing can type into a Claude session from
  // outside; otherwise a new linked session opens with the request.
  const discussInClaude = async (cardIds: number[], task?: string) => {
    // Not known yet (or the last read failed): ask before deciding, so a working linked
    // session is never cut off by opening a new one.
    const current = link ?? (await refreshLink())
    if (!current?.linked) {
      openLinkedSession(cardIds, task)
      return
    }
    setFallbackPrompt(null)
    if (cardIds.length === 0 && !task) {
      setStatus('Your linked Claude session is open in Claude desktop: tick items and say "these" there')
      return
    }
    const text = referenceText(cardIds, task)
    api
      .postSelection(cardIds)
      .then(() => (text ? copyText(text) : Promise.resolve(false)))
      .then((copied) =>
        setStatus(
          copied
            ? 'Copied for your linked Claude session: paste it there'
            : 'Selected for your linked Claude session: say "these" there',
        ),
      )
      .catch(claudeFailed)
  }

  // A job (Process inbox) runs in its own new session, not in the linked conversation.
  const runInClaude = (prompt: string) => {
    setFallbackPrompt(null)
    // The job's prompt names no cards, and the linked session's "these" are left as they are.
    api
      .openClaude(prompt, undefined, false)
      .then(() => setStatus('Opened in Claude desktop'))
      .catch(claudeFailed)
  }

  return (
    <main className="app-shell bg-canvas">
      {/* Centered readable column (mockup .wrap); width is a settings slider. The
          shell is pinned to the viewport height, so this column is a flex column: a
          fixed header above a single flex-filling tab region. */}
      <div
        className="mx-auto flex w-full min-h-0 flex-1 flex-col px-6 pt-5"
        style={{ maxWidth: 'var(--layout-max-width)' }}
      >
        {/* App header: title, status, and the tab nav. Fixed at the top of the shell;
            the tab region below scrolls, so this no longer needs sticky positioning. */}
        <div className="flex-none bg-canvas pb-3 pt-1">
          <header className="mb-3 flex items-center justify-between gap-3">
            <h1
              className="flex items-center gap-2 font-bold text-ink"
              style={{ fontSize: 'var(--font-size-headline)' }}
            >
              {/* Same Lucide telescope the Obsidian ribbon uses (ISC license). */}
              <Telescope size={20} className="text-accent" aria-hidden />
              Spyglass
            </h1>
            <span className="mr-auto text-muted" style={{ fontSize: 'var(--font-size-meta)' }}>
              {status}
              {fallbackPrompt !== null && (
                <>
                  {' '}
                  <CopyPromptButton
                    prompt={fallbackPrompt}
                    onDone={() => {
                      setFallbackPrompt(null)
                      setStatus('Prompt copied: paste it into a new Claude session')
                    }}
                  />
                </>
              )}
            </span>
            <LinkIndicator
              status={link}
              onOpen={() => openLinkedSession()}
              onEnd={() => {
                api.endLink().then(() => refreshLink()).catch(() => {})
              }}
            />
            {/* App-level zoom control: persists across reloads via localStorage (F-task-5). */}
            <ZoomControl />
          </header>
          <nav>
            <SegmentedControl options={TABS} value={tab} onChange={setTab} ariaLabel="Tabs" />
          </nav>
        </div>

        {/* Tab region: fills the remaining height. Brief, Feeds, and the Workspace
            each pin their own top bar and scroll only their body; the simpler
            list/table tabs scroll as a whole inside `.tab-scroll`. */}
        <div className="flex min-h-0 flex-1 flex-col">
          {tab === 'brief' && (
            <BriefTab
              onOpenClaude={discussInClaude}
              onCardLink={(id) => {
                // Route a brief's card: link into the workspace reader.
                setOpenCardRequest(id)
                setTab('workspace')
              }}
            />
          )}
          {tab === 'inbox' && <InboxTab onOpenClaude={discussInClaude} onRunJob={runInClaude} />}
          {tab === 'workspace' && (
            <WorkspaceView
              cards={cards}
              refreshing={refreshing}
              onRefresh={forceRefresh}
              onOpenClaude={discussInClaude}
              onUpdate={onUpdate}
              onMerge={onMerge}
              onDelete={onDelete}
              onOpenExternal={onOpenExternal}
              onReload={loadCards}
              openCardRequest={openCardRequest}
              onCardRequestHandled={onCardRequestHandled}
            />
          )}
          {tab === 'feeds' && (
            <FeedsTab
              feeds={feeds}
              onUpdate={onFeedUpdate}
              onDelete={onFeedDelete}
              onRefresh={onFeedRefresh}
            />
          )}
          {tab === 'activity' && (
            <div className="tab-scroll">
              <ActivityTab runs={runs} />
            </div>
          )}
          {tab === 'archive' && (
            <div className="tab-scroll">
              <ArchivedTab cards={archived} onUnarchive={onUnarchive} />
            </div>
          )}
          {tab === 'settings' && (
            <div className="tab-scroll">
              <SettingsTab />
            </div>
          )}
        </div>
      </div>
    </main>
  )
}

export default App

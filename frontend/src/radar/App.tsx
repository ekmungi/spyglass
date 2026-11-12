// The radar app shell: left rail, the main column (a page layer, with the reader opened over it)
// and the assistant panel on the right. The page under an open reader stays mounted and hidden,
// so Back returns to exactly the same place. The import window (#/import) is a small window of
// its own and is shown without the shell. A change of page runs as a view transition
// (shell/useShownRoute.ts); every lucide icon in the app is drawn with the shared stroke.
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { LucideProvider } from 'lucide-react'
import { AssistantPanel } from './assistant/AssistantPanel'
import { ImportPage } from './import/ImportPage'
import { useAssistState, type Surface } from './assistant/assistStore'
import { ClaudeDialogHost } from './claude/ClaudeDialogHost'
import { FeedPage } from './pages/FeedPage'
import { HelpPage } from './pages/HelpPage'
import { TodayPage } from './pages/TodayPage'
import { ReaderPage } from './reader/ReaderPage'
import { arrivedByHistoryStep, getScroll, readerOrigin, routeKey, saveScroll, useRoute, type Route } from './router'
import { NotFound } from './shell/NotFound'
import { Rail } from './shell/Rail'
import { restoreScroll } from './shell/scroll'
import { SecondaryPage } from './shell/secondaryPages'
import { useShownRoute } from './shell/useShownRoute'
import { ICON_STROKE, ToastViewport } from './ui'
import './shell/shell.css'

/** The page for a non-reader route. `active` is false while the reader covers it. */
function PageFor({ route, active }: { route: Route; active: boolean }) {
  switch (route.name) {
    case 'today':
      return <TodayPage day={route.day} active={active} />
    case 'notfound':
      return <NotFound />
    case 'help':
      return <HelpPage task={route.task} />
    case 'feed':
      return <FeedPage params={route.params} active={active} />
    case 'item':
    case 'import':
      return null
    default:
      return <SecondaryPage name={route.name} />
  }
}

/** Root component of the redesigned interface: the import window alone, or the full shell. */
export default function RadarApp() {
  const route = useRoute()
  return (
    // Icons not yet drawn through ui/icons still get the shared stroke from here.
    <LucideProvider strokeWidth={ICON_STROKE}>
      {route.name === 'import' ? <ImportPage token={route.token} error={route.error} /> : <Shell />}
    </LucideProvider>
  )
}

/** The full interface: rail, pages, reader and assistant. */
function Shell() {
  // The route on screen: it trails the address by one frame while a page-change transition
  // captures the old screen, and equals it otherwise.
  const route = useShownRoute()
  // The page under the reader: where the reader was opened from. After a reload or a deep link
  // the router's history entry still knows it; only a reader opened cold falls back to Today.
  const [lastPage, setLastPage] = useState<Route>(route.name === 'item' ? (readerOrigin() ?? { name: 'today' }) : route)
  // Remember the last non-reader route (state adjusted during render, as React recommends for
  // values derived from a changing input).
  if (route.name !== 'item' && route !== lastPage) setLastPage(route)
  // Browser Back/Forward can land on a reader that was opened from a different page than the one
  // shown now; its history entry says which page it belongs over.
  if (route.name === 'item') {
    const origin = readerOrigin()
    if (origin && routeKey(origin) !== routeKey(lastPage)) setLastPage(origin)
  }
  const reading = route.name === 'item'
  const page = reading ? lastPage : route
  const pageKey = routeKey(page)
  const pageKeyRef = useRef(pageKey)
  const pageLayerRef = useRef<HTMLDivElement>(null)
  const assist = useAssistState()

  // Restore the remembered scroll offset whenever the page under the reader changes.
  useLayoutEffect(() => {
    pageKeyRef.current = pageKey
    const element = pageLayerRef.current
    if (!element) return
    // Only Back/Forward returns to a remembered place; arriving any other way starts at the top.
    const back = arrivedByHistoryStep()
    if (!back) saveScroll(pageKey, 0)
    return restoreScroll(element, back ? getScroll(pageKey) : 0)
  }, [pageKey])

  useEffect(() => {
    document.title = 'Spyglass'
  }, [])

  const surface: Surface | null = reading ? 'reader' : route.name === 'today' ? 'today' : route.name === 'feed' ? 'feed' : null
  const showAssistant = surface !== null && assist.open[surface] && assist.target !== null

  return (
    <div className="r-app" data-assistant={showAssistant ? 'open' : 'closed'}>
      <a
        className="r-skip"
        href="#r-main-content"
        onClick={(event) => {
          // Move focus to the content without changing the address (a bare #fragment is not a route).
          event.preventDefault()
          document.getElementById('r-main-content')?.focus()
        }}
      >
        Skip to content
      </a>
      <Rail active={page.name} />
      <main className="r-main" id="r-main-content" tabIndex={-1}>
        <div
          ref={pageLayerRef}
          className="r-layer r-layer--page"
          data-hidden={reading ? 'true' : undefined}
          inert={reading}
          aria-hidden={reading || undefined}
          onScroll={(event) => saveScroll(pageKeyRef.current, event.currentTarget.scrollTop)}
        >
          <PageFor route={page} active={!reading} />
        </div>
        {route.name === 'item' && <ReaderPage key={route.id} id={route.id} />}
      </main>
      {showAssistant && surface && <AssistantPanel surface={surface} />}
      <ClaudeDialogHost />
      <ToastViewport />
    </div>
  )
}

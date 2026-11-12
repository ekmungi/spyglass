// Find papers page: type a topic, get the few papers that matter with one line on how each relates
// to the reader's field. The last result stays in memory so navigating away and back loses nothing.
import './papers/papers.css'
import { useId, useState, useSyncExternalStore, type FormEvent } from 'react'
import { errorMessage } from '../api/errors'
import type { PaperResult } from '../api/types'
import { Button, Chip, EmptyState, SectionHeading, Skeleton } from '../ui'
import { captureLink, loadProfileTopics, searchPapers } from './papers/api'
import { PaperRow } from './papers/PaperRow'
import { getSnapshot, markAdded, runSearch, subscribe } from './papers/store'
import { useElapsed } from './sources/useElapsed'
import { useLoad } from './sources/useLoad'

/** How many example chips to offer from the profile topics. */
const MAX_CHIPS = 4

/** The Find papers page (no props). */
export default function PapersPage() {
  const memory = useSyncExternalStore(subscribe, getSnapshot)
  const [draft, setDraft] = useState(memory.topic)
  const [adding, setAdding] = useState<ReadonlySet<string>>(new Set())
  const [addErrors, setAddErrors] = useState<Readonly<Record<string, string>>>({})
  const topics = useLoad<string[]>((signal) => loadProfileTopics(signal))
  const inputId = useId()
  const loading = memory.status === 'loading'
  const seconds = useElapsed(loading)
  const chips = (topics.data ?? []).slice(0, MAX_CHIPS)

  const search = (topic: string) => {
    const text = topic.trim()
    if (!text) return
    setDraft(text)
    void runSearch(text, (value) => searchPapers(value, 8))
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    search(draft)
  }

  const add = async (paper: PaperResult) => {
    setAdding((current) => new Set(current).add(paper.url))
    setAddErrors((current) => {
      const next = { ...current }
      delete next[paper.url]
      return next
    })
    try {
      const item = await captureLink({ url: paper.url })
      markAdded(paper.url, item.id)
    } catch (cause) {
      setAddErrors((current) => ({ ...current, [paper.url]: errorMessage(cause) }))
    } finally {
      setAdding((current) => {
        const next = new Set(current)
        next.delete(paper.url)
        return next
      })
    }
  }

  return (
    <div className="r-page">
      <h1 className="r-page-title">Find papers</h1>
      <p className="r-page-meta">The few papers that matter for a topic, ranked against your profile.</p>

      <form className="rpp-search" onSubmit={submit} noValidate>
        <label htmlFor={inputId} className="rpp-search__label">
          What do you want to read about?
        </label>
        <div className="rpp-search__row">
          <input
            id={inputId}
            className="r-input rpp-search__input"
            value={draft}
            disabled={loading}
            onChange={(event) => setDraft(event.target.value)}
          />
          <Button type="submit" variant="primary" disabled={loading || !draft.trim()}>
            Find papers
          </Button>
        </div>
        {chips.length > 0 && (
          <div className="rpp-chips" role="group" aria-label="Topics from your profile">
            {chips.map((name) => (
              <Chip key={name} selected={memory.topic === name && memory.status !== 'idle'} disabled={loading} onClick={() => search(name)}>
                {name}
              </Chip>
            ))}
          </div>
        )}
      </form>

      <div role="status" aria-live="polite" className="rpp-status">
        {loading && (
          <p className="r-meta">
            Searching and ranking papers for “{memory.topic}”. This usually takes 10 to 40 seconds ({seconds}s so far).
          </p>
        )}
      </div>

      {loading && (
        <div aria-hidden="true" className="rpp-skeleton">
          <Skeleton width="70%" height={22} />
          <Skeleton lines={2} />
          <Skeleton width="60%" height={22} />
          <Skeleton lines={2} />
        </div>
      )}

      {memory.status === 'error' && (
        <div className="rpp-error" role="alert">
          <p className="r-error-text">{memory.error}</p>
          <Button onClick={() => search(memory.topic)}>Try again</Button>
        </div>
      )}

      {memory.status === 'done' && memory.papers.length === 0 && (
        <EmptyState
          title="No papers matched this topic."
          body={memory.notice ?? 'Try a broader topic or different words. Names of methods and venues work well.'}
        />
      )}

      {memory.status === 'done' && memory.papers.length > 0 && memory.notice && <p className="r-meta rpp-notice">{memory.notice}</p>}

      {memory.status === 'done' && memory.papers.length > 0 && (
        <section aria-labelledby="papers-results">
          <SectionHeading id="papers-results" note={`${memory.papers.length} ${memory.papers.length === 1 ? 'paper' : 'papers'}`}>
            {`Results for “${memory.topic}”`}
          </SectionHeading>
          <ol className="r-rows rpp-list">
            {memory.papers.map((paper) => (
              <PaperRow
                key={paper.url}
                paper={paper}
                itemId={paper.item_id ?? memory.added[paper.url] ?? null}
                adding={adding.has(paper.url)}
                addError={addErrors[paper.url] ?? null}
                onAdd={(value) => void add(value)}
              />
            ))}
          </ol>
        </section>
      )}
    </div>
  )
}

// HelpPage (#/help, #/help/<task-id>): "How to". A search field filters the tasks, which are grouped
// under plain headings; each opens in place. A deep link opens its task and scrolls it into view.
import { useEffect, useState } from 'react'
import { filterGroups, findTask, isAvailable } from '../help/tasks'
import { HelpTaskCard } from '../help/HelpTaskCard'
import { useFilingConfiguredState } from '../state/filingConfigured'
import { EmptyState, IconSearch, SectionHeading } from '../ui'
import '../help/help.css'

/** What a deep link to a task that needs filing shows where filing is not set up. */
export const NOT_SET_UP = 'This function is not set up on this Spyglass.'

/** The How to page; `task` is the id named in the address, if any. */
export function HelpPage({ task }: { task?: string }) {
  const [query, setQuery] = useState('')
  const filingState = useFilingConfiguredState()
  const filingOn = filingState === true
  const [openId, setOpenId] = useState<string | null>(findTask(task)?.id ?? null)
  const named = findTask(task)
  const missing = named !== undefined && !isAvailable(named, filingOn) && filingState === false
  // A new address (for example a Take me there link from elsewhere) opens the task it names.
  const [seen, setSeen] = useState(task)
  if (seen !== task) {
    setSeen(task)
    setOpenId(findTask(task)?.id ?? null)
  }
  useEffect(() => {
    if (openId) document.getElementById(`help-${openId}`)?.scrollIntoView?.({ block: 'start' })
  }, [openId])
  const groups = filterGroups(query, filingOn)
  return (
    <div className="r-page">
      <h1 className="r-page-title">How to</h1>
      <p className="r-page-meta">Short steps for each thing Spyglass can do, and a button that takes you to the right screen.</p>
      <label className="rh-search">
        <IconSearch size={16} />
        <span className="r-sr-only">Search the tasks</span>
        <input type="search" value={query} placeholder="Search, for example feed, topic or file" onChange={(event) => setQuery(event.target.value)} />
      </label>
      {missing && (
        <p className="r-meta" role="status">
          {NOT_SET_UP}
        </p>
      )}
      {groups.length === 0 && <EmptyState title="No task matches that" body="Try one word, such as feed, paper or save." />}
      {groups.map((group) => (
        <section key={group.id} aria-labelledby={`help-group-${group.id}`} className="rh-group">
          <SectionHeading id={`help-group-${group.id}`}>{group.heading}</SectionHeading>
          <ul className="r-rows rh-list">
            {group.tasks.map((item) => (
              <HelpTaskCard key={item.id} task={item} open={openId === item.id} onToggle={() => setOpenId(openId === item.id ? null : item.id)} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  )
}

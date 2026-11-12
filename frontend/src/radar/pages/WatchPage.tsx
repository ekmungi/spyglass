// Watch page: the topics you follow, then the companies, labs and regulators Spyglass checks every day, grouped,
// with suggestions waiting for a yes. One Add button opens every way to add; a group menu and an AI review tidy the list.
import './watch/watch.css'
import { useCallback, useMemo, useState } from 'react'
import { errorMessage } from '../api/errors'
import type { RemovedWatchEntity, SectionKey, WatchApplyResponse, WatchGroupBody } from '../api/types'
import { Button, Dialog, EmptyState, IconAdd, SectionHeading, Skeleton, toast, type MenuItem } from '../ui'
import {
  addEntry,
  changeEntry,
  createTrack,
  deleteWatch,
  discoverTopic,
  getWatch,
  patchWatchGroup,
  restoreWatchGroup,
  type EntryFields,
  type WatchEntry,
  type WatchRegister,
} from './watch/api'
import { AddDialog } from './watch/AddDialog'
import { EntityDialog } from './watch/EntityDialog'
import type { FollowFields } from './watch/FollowPane'
import { GroupHeading, type GroupMenuAction } from './watch/GroupHeading'
import { GroupDialog, type GroupDialogState } from './watch/GroupDialogs'
import { categoryNames, organizeRegister, type OrganizedGroup } from './watch/organize'
import { describeApplied } from './watch/reviewText'
import { ReviewPanel } from './watch/ReviewPanel'
import { TopicsSection } from './watch/TopicsSection'
import { WatchRow } from './watch/WatchRow'
import { useLoad } from './sources/useLoad'

type DialogState = { kind: 'edit'; entry: WatchEntry; round: number } | { kind: 'remove'; entry: WatchEntry } | null

const EXPLAINER =
  "Spyglass searches the news for each of these once a day. What it finds goes into your Feed, and the important ones appear in your brief under 'On your watch list'."

/** The register without the extra keys a group or review answer carries. */
function registerOf<T extends WatchRegister>({ categories, suggested }: T): WatchRegister {
  return { categories, suggested }
}

/** The Watch page (no props): the register by group, suggestions, topics, and every way to add or tidy. */
export default function WatchPage() {
  const { data, error, loading, reload, replace } = useLoad<WatchRegister>((signal) => getWatch(signal), 'watch')
  const [busyId, setBusyId] = useState<number | null>(null)
  const [busyGroup, setBusyGroup] = useState<string | null>(null)
  const [dialog, setDialog] = useState<DialogState>(null)
  const [groupDialog, setGroupDialog] = useState<GroupDialogState>(null)
  const [groupProblem, setGroupProblem] = useState<string | null>(null)
  const [removing, setRemoving] = useState(false)
  const [adding, setAdding] = useState(false)
  const [reviewing, setReviewing] = useState(false)
  const [topicsToken, setTopicsToken] = useState(0)

  const organized = useMemo(() => (data ? organizeRegister(data) : null), [data])
  const closeDialog = useCallback(() => setDialog(null), [])
  const closeAdd = useCallback(() => setAdding(false), [])
  const closeReview = useCallback(() => setReviewing(false), [])
  const closeGroupDialog = useCallback(() => {
    setGroupDialog(null)
    setGroupProblem(null)
  }, [])

  /** Run one change on one name, reload the register, and report a failure in words. */
  const act = async (entry: WatchEntry, run: () => Promise<unknown>, done?: string, undo?: () => Promise<unknown>) => {
    setBusyId(entry.id)
    try {
      await run()
      reload()
      if (done) {
        toast(done, {
          action: undo
            ? {
                label: 'Undo',
                onClick: () => {
                  undo().then(reload, (cause) => toast(errorMessage(cause), { tone: 'error' }))
                },
              }
            : undefined,
        })
      }
    } catch (cause) {
      toast(errorMessage(cause), { tone: 'error' })
    } finally {
      setBusyId(null)
    }
  }

  const accept = (entry: WatchEntry) => act(entry, () => changeEntry(entry.id, { status: 'active' }), `Now watching ${entry.name}`)
  const dismiss = (entry: WatchEntry) =>
    act(entry, () => changeEntry(entry.id, { status: 'muted' }), `Dismissed ${entry.name}`, () => changeEntry(entry.id, { status: 'suggested' }))
  const mute = (entry: WatchEntry) =>
    act(entry, () => changeEntry(entry.id, { status: 'muted' }), `Muted ${entry.name}`, () => changeEntry(entry.id, { status: 'active' }))
  const unmute = (entry: WatchEntry) => act(entry, () => changeEntry(entry.id, { status: 'active' }), `Watching ${entry.name} again`)

  const saveEdit = async (fields: EntryFields) => {
    if (dialog?.kind !== 'edit') return
    await changeEntry(dialog.entry.id, fields)
    setDialog(null)
    reload()
    toast('Changes saved')
  }

  const addOrganisation = async (fields: EntryFields) => {
    await addEntry(fields)
    setAdding(false)
    reload()
    toast(`Now watching ${fields.name}`)
  }

  const followTopic = async (fields: FollowFields) => {
    await createTrack({ label: fields.label, query: fields.query, section: fields.section as SectionKey, kind: 'topic' })
    setAdding(false)
    setTopicsToken((value) => value + 1)
    toast(`Now following ${fields.label}`)
  }

  const confirmRemove = async () => {
    if (dialog?.kind !== 'remove') return
    const entry = dialog.entry
    setRemoving(true)
    try {
      await deleteWatch(entry.id)
      setDialog(null)
      reload()
      toast(`Removed ${entry.name}`)
    } catch (cause) {
      toast(errorMessage(cause), { tone: 'error' })
    } finally {
      setRemoving(false)
    }
  }

  /** Put back entries a group removal or a review took out, and show the register as it is then. */
  const restore = (removed: RemovedWatchEntity[]) =>
    restoreWatchGroup(removed).then(
      (result) => {
        replace(registerOf(result))
        toast(`Restored ${removed.length} ${removed.length === 1 ? 'name' : 'names'}`)
      },
      (cause: unknown) => toast(errorMessage(cause), { tone: 'error' }),
    )

  /** One whole-group change. The answer is the fresh register, so no second request is needed. */
  const changeGroup = async (body: WatchGroupBody, message: (removed: RemovedWatchEntity[]) => string, undo?: (removed: RemovedWatchEntity[]) => Promise<unknown>) => {
    setBusyGroup(body.category)
    setGroupProblem(null)
    try {
      const result = await patchWatchGroup(body)
      replace(registerOf(result))
      setGroupDialog(null)
      toast(message(result.removed), { action: undo ? { label: 'Undo', onClick: () => void undo(result.removed) } : undefined })
    } catch (cause) {
      const text = errorMessage(cause)
      if (groupDialog) setGroupProblem(text)
      else toast(text, { tone: 'error' })
    } finally {
      setBusyGroup(null)
    }
  }

  const onGroupAction = (group: OrganizedGroup, action: GroupMenuAction) => {
    if (action === 'pause') void changeGroup({ category: group.name, action }, () => `Paused ${group.name}`)
    else if (action === 'resume') void changeGroup({ category: group.name, action }, () => `Watching ${group.name} again`)
    else {
      const count = data?.categories.find((category) => category.name === group.name)?.entities.length ?? group.entities.length
      setGroupProblem(null)
      setGroupDialog({ kind: action, name: group.name, count })
    }
  }

  const submitGroupName = (kind: 'rename' | 'move', to: string) => {
    if (!groupDialog) return
    const from = groupDialog.name
    if (kind === 'rename') {
      void changeGroup({ category: from, action: 'rename', to }, () => `Renamed ${from} to ${to}`, () =>
        patchWatchGroup({ category: to, action: 'rename', to: from }).then((result) => replace(registerOf(result))),
      )
    } else {
      void changeGroup({ category: from, action: 'move', to }, () => `Moved every name in ${from} to ${to}`)
    }
  }

  const applied = (result: WatchApplyResponse) => {
    replace(registerOf(result))
    setReviewing(false)
    toast(describeApplied(result.applied), {
      action: result.removed.length > 0 ? { label: 'Undo removal', onClick: () => void restore(result.removed) } : undefined,
    })
  }

  const openEdit = (entry: WatchEntry) => setDialog((current) => ({ kind: 'edit', entry, round: (current?.kind === 'edit' ? current.round : 0) + 1 }))

  const menuFor = (entry: WatchEntry): MenuItem[] => [
    { id: 'edit', label: 'Edit', onSelect: () => openEdit(entry) },
    entry.status === 'muted'
      ? { id: 'unmute', label: 'Watch again', onSelect: () => void unmute(entry) }
      : { id: 'mute', label: 'Mute', hint: 'Stop checking', onSelect: () => void mute(entry) },
    { id: 'remove', label: 'Remove…', onSelect: () => setDialog({ kind: 'remove', entry }) },
  ]

  const suggested = data?.suggested ?? []
  const empty = organized !== null && organized.groups.length === 0 && organized.muted.length === 0 && suggested.length === 0
  const groupNames = data ? categoryNames(data) : []

  return (
    <div className="r-page">
      <div className="rw-head">
        <h1 className="r-page-title">Watch</h1>
        <div className="rw-head__actions">
          <Button variant="quiet" size="sm" onClick={() => setReviewing(true)}>
            Review with AI
          </Button>
          <Button variant="secondary" icon={<IconAdd size={16} />} onClick={() => setAdding(true)}>
            Add
          </Button>
        </div>
      </div>
      <p className="r-page-meta">{EXPLAINER}</p>

      <TopicsSection refreshToken={topicsToken} />

      {loading && !data && (
        <div aria-busy="true" aria-label="Loading your watch list" className="rw-skeleton">
          <Skeleton width="30%" height={14} />
          <Skeleton lines={3} />
          <Skeleton width="30%" height={14} />
          <Skeleton lines={3} />
        </div>
      )}

      {error && (
        <div className="rw-error" role="alert">
          <p className="r-error-text">{data ? `Could not refresh the list. ${error}` : error}</p>
          <Button onClick={reload}>Try again</Button>
        </div>
      )}

      {suggested.length > 0 && (
        <section aria-labelledby="watch-suggested" className="rw-section">
          <SectionHeading id="watch-suggested" note="Waiting for your yes">
            Suggested
          </SectionHeading>
          <ul className="r-rows">
            {suggested.map((entry) => (
              <WatchRow
                key={entry.id}
                entry={entry}
                busy={busyId === entry.id}
                actions={
                  <>
                    <Button size="sm" variant="secondary" disabled={busyId === entry.id} aria-label={`Accept ${entry.name}`} onClick={() => void accept(entry)}>
                      Accept
                    </Button>
                    <Button size="sm" variant="quiet" disabled={busyId === entry.id} aria-label={`Dismiss ${entry.name}`} onClick={() => void dismiss(entry)}>
                      Dismiss
                    </Button>
                  </>
                }
              />
            ))}
          </ul>
        </section>
      )}

      {organized?.groups.map((group, index) => (
        <section key={group.name} aria-labelledby={`watch-group-${index}`} className={`rw-section${group.paused ? ' rw-paused' : ''}`}>
          <GroupHeading id={`watch-group-${index}`} group={group} busy={busyGroup === group.name} onAction={(action) => onGroupAction(group, action)} />
          <ul className="r-rows">
            {group.entities.map((entry) => (
              <WatchRow key={entry.id} entry={entry} busy={busyId === entry.id} menu={menuFor(entry)} />
            ))}
          </ul>
        </section>
      ))}

      {organized && organized.muted.length > 0 && (
        <details className="rw-section rw-muted">
          <summary>Muted ({organized.muted.length})</summary>
          <ul className="r-rows">
            {organized.muted.map((entry) => (
              <WatchRow key={entry.id} entry={entry} busy={busyId === entry.id} menu={menuFor(entry)} />
            ))}
          </ul>
        </details>
      )}

      {empty && (
        <EmptyState
          title="Nothing on your watch list yet"
          body="Use Add to find who matters for a topic, follow a topic, or add a name yourself."
          action={<Button onClick={() => setAdding(true)}>Add something to watch</Button>}
        />
      )}

      {adding && (
        <AddDialog
          categories={groupNames}
          onClose={closeAdd}
          discover={discoverTopic}
          onDiscovered={reload}
          onFollow={followTopic}
          onAddOrganisation={addOrganisation}
        />
      )}

      {reviewing && <ReviewPanel onClose={closeReview} onApplied={applied} />}

      {dialog?.kind === 'edit' && (
        <EntityDialog key={`${dialog.entry.id}-${dialog.round}`} open entry={dialog.entry} categories={groupNames} onClose={closeDialog} onSave={saveEdit} />
      )}

      {groupDialog && (
        <GroupDialog
          state={groupDialog}
          others={(data?.categories ?? []).map((category) => category.name).filter((name) => name !== groupDialog.name)}
          busy={busyGroup !== null}
          problem={groupProblem}
          onClose={closeGroupDialog}
          onRename={(to) => submitGroupName('rename', to)}
          onMove={(to) => submitGroupName('move', to)}
          onRemove={() =>
            void changeGroup(
              { category: groupDialog.name, action: 'remove' },
              (removed) => `Removed ${groupDialog.name} (${removed.length} ${removed.length === 1 ? 'name' : 'names'})`,
              (removed) => restore(removed),
            )
          }
        />
      )}

      <Dialog
        open={dialog?.kind === 'remove'}
        onClose={closeDialog}
        title={dialog?.kind === 'remove' ? `Remove ${dialog.entry.name}?` : 'Remove'}
        footer={
          <>
            <Button variant="quiet" onClick={closeDialog}>
              Cancel
            </Button>
            <Button variant="primary" disabled={removing} onClick={() => void confirmRemove()}>
              Remove
            </Button>
          </>
        }
      >
        <p className="r-meta">Spyglass stops checking this name and forgets which items mention it. The items themselves stay in your feed.</p>
      </Dialog>
    </div>
  )
}

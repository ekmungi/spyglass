// Watch page: the companies, labs and regulators Spyglass checks every day as chips, one row per group,
// and the Paused list; then the suggested organisations as chips, one row per profile section; the
// Not of interest list; and the topics you follow. One click on a chip changes a name in place. One
// Add button opens every way to add; a group menu and an AI review tidy the list.
import './watch/watch.css'
import { useCallback, useState } from 'react'
import { errorMessage } from '../api/errors'
import type { RemovedWatchEntity, SectionKey, WatchApplyResponse, WatchGroupBody, WatchGroupResponse } from '../api/types'
import { navigate } from '../router'
import { Button, EmptyState, IconAdd, Skeleton, toast, type MenuItem } from '../ui'
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
import { AddDialog, type AddStep } from './watch/AddDialog'
import { EntityDialog } from './watch/EntityDialog'
import type { FollowFields } from './watch/FollowPane'
import type { GroupMenuAction } from './watch/GroupHeading'
import { GroupDialog, type GroupDialogState } from './watch/GroupDialogs'
import { MoveDialog } from './watch/MoveDialog'
import { RemoveNameDialog } from './watch/RemoveNameDialog'
import { categoryNames, groupSteps, type LayoutGroup } from './watch/organize'
import { RejectedList } from './watch/RejectedList'
import { describeApplied } from './watch/reviewText'
import { ReviewPanel } from './watch/ReviewPanel'
import { SuggestedSection } from './watch/SuggestedSection'
import { TopicsSection } from './watch/TopicsSection'
import { WatchingSection } from './watch/WatchingSection'
import { useWatchLayout } from './watch/useWatchLayout'
import { useLoad } from './sources/useLoad'

/** The open per-name dialog; `group` is the group the name is shown in or labelled with. */
type DialogState =
  | { kind: 'edit'; entry: WatchEntry; group: string; round: number }
  | { kind: 'move'; entry: WatchEntry; group: string }
  | { kind: 'remove'; entry: WatchEntry }
  | null

const EXPLAINER =
  "Spyglass searches the news for each of these once a day. What it finds goes into your Feed, and the important ones appear in your brief under 'On your watch list'."

/** The register without the extra keys a group or review answer carries. */
function registerOf<T extends WatchRegister>({ categories, suggested, rejected, sections }: T): WatchRegister {
  return { categories, suggested, rejected, sections }
}

/** The Watch page (no props): the register by group, suggestions, topics, and every way to add or tidy. */
export default function WatchPage() {
  const loaded = useLoad<WatchRegister>((signal) => getWatch(signal), 'watch')
  const { data, error, loading } = loaded
  const [busyGroup, setBusyGroup] = useState<string | null>(null)
  const [dialog, setDialog] = useState<DialogState>(null)
  const [groupDialog, setGroupDialog] = useState<GroupDialogState>(null)
  const [groupProblem, setGroupProblem] = useState<string | null>(null)
  const [removing, setRemoving] = useState(false)
  // The step the Add dialog opens at while it is open.
  const [adding, setAdding] = useState<AddStep | null>(null)
  const [reviewing, setReviewing] = useState(false)
  const [topicsToken, setTopicsToken] = useState(0)

  // Laid out once per load; a chip click changes only that chip's look, and the chip keeps its place
  // until an action that changes the structure. Every reload and replace below is such an action.
  const { layout, switching, toggle, change, changeMany, restructure } = useWatchLayout(data, loaded.remember)
  const reload = () => {
    restructure()
    loaded.reload()
  }
  const replace = (next: WatchRegister) => {
    restructure()
    loaded.replace(next)
  }

  const closeDialog = useCallback(() => setDialog(null), [])
  const closeAdd = useCallback(() => setAdding(null), [])
  const closeReview = useCallback(() => setReviewing(false), [])
  const closeGroupDialog = useCallback(() => {
    setGroupDialog(null)
    setGroupProblem(null)
  }, [])

  /** Move one name to another group; the rows change, so the list is loaded again. */
  const moveName = async (entry: WatchEntry, to: string) => {
    const back = entry.category
    await changeEntry(entry.id, { category: to })
    setDialog(null)
    reload()
    toast(`Moved ${entry.name} to ${to}.`, {
      action: {
        label: 'Undo',
        onClick: () => {
          changeEntry(entry.id, { category: back }).then(reload, (cause) => toast(errorMessage(cause), { tone: 'error' }))
        },
      },
    })
  }

  const saveEdit = async (fields: EntryFields) => {
    if (dialog?.kind !== 'edit') return
    await changeEntry(dialog.entry.id, fields)
    setDialog(null)
    reload()
    toast('Changes saved')
  }

  const addOrganisation = async (fields: EntryFields) => {
    await addEntry(fields)
    setAdding(null)
    reload()
    toast(`Now watching ${fields.name}`)
  }

  const followTopic = async (fields: FollowFields) => {
    await createTrack({ label: fields.label, query: fields.query, section: fields.section as SectionKey, kind: 'topic' })
    setAdding(null)
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

  /**
   * One whole-group change, sent `times` times in a row (a move past hidden groups). The answer is the
   * fresh register, so no second request is needed; the page is laid out again from it. When a later
   * step fails, the page shows the answer of the last step that went through, which is how the
   * service has it, so the next move is counted from there.
   */
  const changeGroup = async (
    body: WatchGroupBody,
    message: (removed: RemovedWatchEntity[]) => string,
    undo?: (removed: RemovedWatchEntity[]) => Promise<unknown>,
    times = 1,
  ) => {
    setBusyGroup(body.category)
    setGroupProblem(null)
    let last: WatchGroupResponse | null = null
    try {
      for (let step = 0; step < times; step += 1) last = await patchWatchGroup(body)
      const result = last
      if (!result) return
      replace(registerOf(result))
      setGroupDialog(null)
      toast(message(result.removed), { action: undo ? { label: 'Undo', onClick: () => void undo(result.removed) } : undefined })
    } catch (cause) {
      if (last) replace(registerOf(last))
      const text = errorMessage(cause)
      if (groupDialog) setGroupProblem(text)
      else toast(text, { tone: 'error' })
    } finally {
      setBusyGroup(null)
    }
  }

  const onGroupAction = (group: LayoutGroup, action: GroupMenuAction) => {
    if (action === 'pause') void changeGroup({ category: group.name, action }, () => `Paused ${group.name}`)
    else if (action === 'resume') void changeGroup({ category: group.name, action }, () => `Watching ${group.name} again`)
    else if (action === 'up' || action === 'down') {
      const order = (data?.categories ?? []).map((category) => category.name)
      const times = groupSteps(order, layout?.groups.map((shown) => shown.name) ?? [], group.name, action)
      if (times > 0) void changeGroup({ category: group.name, action }, () => `Moved ${group.name} ${action}`, undefined, times)
    } else {
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

  const openDetails = (entry: WatchEntry, group: string) =>
    setDialog((current) => ({ kind: 'edit', entry, group, round: (current?.kind === 'edit' ? current.round : 0) + 1 }))

  /** The rare actions on a chip; the one-click switch is the chip itself. */
  const menuFor = (entry: WatchEntry, group: string): MenuItem[] => [
    { id: 'details', label: 'Details', onSelect: () => openDetails(entry, group) },
    { id: 'move', label: 'Move to another group…', onSelect: () => setDialog({ kind: 'move', entry, group }) },
    { id: 'items', label: 'See its items in the Feed', onSelect: () => navigate({ name: 'feed', params: { q: entry.name } }) },
    { id: 'remove', label: 'Remove…', onSelect: () => setDialog({ kind: 'remove', entry }) },
  ]

  const watching = layout !== null && (layout.groups.length > 0 || layout.paused.length > 0)
  const empty = layout !== null && !watching && layout.rows.every((row) => row.entities.length === 0)
  const groupNames = data ? categoryNames(data) : []

  return (
    <div className="r-page rw-page">
      <div className="rw-head">
        <h1 className="r-page-title">Watch</h1>
        <div className="rw-head__actions">
          <Button variant="quiet" size="sm" onClick={() => setReviewing(true)}>
            Review with AI
          </Button>
          <Button variant="secondary" icon={<IconAdd size={16} />} onClick={() => setAdding('choose')}>
            Add
          </Button>
        </div>
      </div>
      <p className="r-page-meta">{EXPLAINER}</p>

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

      {layout && watching && (
        <WatchingSection layout={layout} busyIds={switching} busyGroup={busyGroup} menuFor={menuFor} onToggle={toggle} onGroupAction={onGroupAction} />
      )}

      {empty && (
        <EmptyState
          title="Nothing on your watch list yet"
          body="Use Add to find who matters for a topic, follow a topic, or add a name yourself."
          action={<Button onClick={() => setAdding('choose')}>Add something to watch</Button>}
        />
      )}

      {layout && <SuggestedSection rows={layout.rows} busyIds={switching} change={change} changeMany={changeMany} />}
      {layout && <RejectedList rejected={layout.rejected} rows={layout.rows} change={change} />}
      <TopicsSection refreshToken={topicsToken} onFollow={() => setAdding('follow')} />

      {adding && (
        <AddDialog
          start={adding}
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
        <EntityDialog
          key={`${dialog.entry.id}-${dialog.round}`}
          open
          entry={dialog.entry}
          group={dialog.group}
          categories={groupNames}
          onClose={closeDialog}
          onSave={saveEdit}
        />
      )}

      {dialog?.kind === 'move' && (
        <MoveDialog
          key={dialog.entry.id}
          entry={dialog.entry}
          from={dialog.group}
          others={(data?.categories ?? []).map((category) => category.name).filter((name) => name !== dialog.group)}
          onClose={closeDialog}
          onMove={(to) => moveName(dialog.entry, to)}
        />
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

      <RemoveNameDialog
        open={dialog?.kind === 'remove'}
        name={dialog?.kind === 'remove' ? dialog.entry.name : null}
        busy={removing}
        onClose={closeDialog}
        onRemove={() => void confirmRemove()}
      />
    </div>
  )
}

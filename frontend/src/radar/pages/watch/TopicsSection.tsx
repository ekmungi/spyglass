// TopicsSection: "Topics you follow", the group above the organisations register on the Watch page.
// Each topic can be edited, paused and resumed, or stopped (with an undo).
import { useEffect, useRef, useState } from 'react'
import { errorMessage } from '../../api/errors'
import type { Track } from '../../api/types'
import { Button, EmptyState, SectionHeading, Skeleton, toast, type MenuItem } from '../../ui'
import { useLoad } from '../sources/useLoad'
import { createTrack, deleteTrack, getTracks, patchTrack } from './api'
import { TrackEditDialog, type TrackFields } from './TrackEditDialog'
import { TrackRow } from './TrackRow'

export interface TopicsSectionProps {
  /** Changes whenever the page has followed a topic from outside this section, so the list reloads. */
  refreshToken?: number
}

/** The followed-topics group; it loads its own list and refreshes after each change. */
export function TopicsSection({ refreshToken = 0 }: TopicsSectionProps = {}) {
  const { data, error, loading, reload } = useLoad<Track[]>((signal) => getTracks(signal), 'tracks')
  const seenToken = useRef(refreshToken)
  useEffect(() => {
    if (seenToken.current === refreshToken) return
    seenToken.current = refreshToken
    reload()
  }, [refreshToken, reload])
  const [busyId, setBusyId] = useState<number | null>(null)
  const [editing, setEditing] = useState<Track | null>(null)

  /** Run one change, refresh the list and report a failure in words. */
  const act = async (track: Track, run: () => Promise<unknown>, done?: string, undo?: () => Promise<unknown>) => {
    setBusyId(track.id)
    try {
      await run()
      reload()
      if (done) {
        toast(done, {
          action: undo ? { label: 'Undo', onClick: () => void undo().then(reload, (cause) => toast(errorMessage(cause), { tone: 'error' })) } : undefined,
        })
      }
    } catch (cause) {
      toast(errorMessage(cause), { tone: 'error' })
    } finally {
      setBusyId(null)
    }
  }

  const pauseOrResume = (track: Track) =>
    act(track, () => patchTrack(track.id, { active: !track.active }), track.active ? `Paused ${track.label}` : `Following ${track.label} again`)

  // Stopping deletes the topic; Undo creates it again with the same settings (its history of finds starts over).
  const stop = (track: Track) =>
    act(
      track,
      () => deleteTrack(track.id),
      `Stopped following ${track.label}`,
      () =>
        createTrack({
          label: track.label,
          query: track.query,
          section: track.section,
          kind: track.kind,
          ...(track.from_item_id ? { from_item_id: track.from_item_id } : {}),
        }),
    )

  const save = async (fields: TrackFields) => {
    if (!editing) return
    await patchTrack(editing.id, fields)
    setEditing(null)
    reload()
    toast('Changes saved')
  }

  const menuFor = (track: Track): MenuItem[] => [
    { id: 'edit', label: 'Edit', onSelect: () => setEditing(track) },
    { id: 'pause', label: track.active ? 'Pause' : 'Resume', hint: track.active ? 'Stop checking for now' : undefined, onSelect: () => void pauseOrResume(track) },
    { id: 'stop', label: 'Stop following', onSelect: () => void stop(track) },
  ]

  const tracks = data ?? []
  return (
    <section aria-labelledby="watch-topics" className="rw-section">
      <SectionHeading id="watch-topics" note={tracks.length > 0 ? `${tracks.length}` : undefined}>
        Topics you follow
      </SectionHeading>

      {loading && !data && (
        <div aria-busy="true" aria-label="Loading the topics you follow" className="rw-skeleton">
          <Skeleton lines={3} />
        </div>
      )}
      {error && (
        <div className="rw-error" role="alert">
          <p className="r-error-text">{data ? `Could not refresh the topics. ${error}` : error}</p>
          <Button onClick={reload}>Try again</Button>
        </div>
      )}
      {data && tracks.length === 0 && (
        <EmptyState title="You are not following any topics yet" body="Use Add, at the top of the page, to follow a topic, or open any article and choose Follow." />
      )}
      {tracks.length > 0 && (
        <ul className="r-rows">
          {tracks.map((track) => (
            <TrackRow key={track.id} track={track} busy={busyId === track.id} menu={menuFor(track)} />
          ))}
        </ul>
      )}
      {editing && <TrackEditDialog key={editing.id} track={editing} onClose={() => setEditing(null)} onSave={save} />}
    </section>
  )
}

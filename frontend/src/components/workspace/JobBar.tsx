// The detailed note's actions in the reader: Prepare detail when there is none; Read,
// File it and Delete while it is unfiled; where it was filed afterwards. Prepare and File run
// as hidden Claude jobs, so this bar also says what the job is doing, or why it failed.
import { BookOpen, FilePlus2, FolderInput, Loader2, RotateCcw, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import { activeLine, failedLine, folderOf, isActive, usageLine } from '../../lib/jobs'
import type { CardJobsState } from '../../lib/useCardJobs'

interface Props {
  jobs: CardJobsState
  onRead: () => void
  // Ask the linked Claude session to move the filed note elsewhere; hidden when absent.
  onMove?: (folder: string) => void
}

const BUTTON =
  'inline-flex items-center gap-1.5 border border-border px-2.5 py-1 text-body hover:border-accent hover:text-accent'
const STYLE = { borderRadius: 'var(--radius-control)', fontSize: 'var(--font-size-actions)' }

export function JobBar({ jobs, onRead, onMove }: Props) {
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const { data, error } = jobs
  if (data === null) return null
  const latest = data.jobs[0]
  const note = data.note
  const filed = note.path && !note.unfiled
  const lastFiling = data.jobs.find((job) => job.kind === 'file-note' && job.status === 'ok')

  return (
    <div className="mb-3.5 flex flex-col gap-1.5" data-testid="job-bar">
      {isActive(latest) ? (
        <div className="flex flex-wrap items-center gap-2 text-muted" style={{ fontSize: 'var(--font-size-actions)' }}>
          <Loader2 size={14} className="animate-spin text-accent" aria-hidden />
          <span role="status">{activeLine(latest)}</span>
          <button type="button" className={BUTTON} style={STYLE} onClick={jobs.cancel}>
            <X size={13} /> Cancel
          </button>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          {!note.path && (
            <button type="button" className={BUTTON} style={STYLE} onClick={() => jobs.start('prepare-detail')}
              title="Claude writes a detailed note in the background and links it to your notes">
              <FilePlus2 size={14} /> Prepare detail
            </button>
          )}
          {note.path && (
            <button type="button" className={BUTTON} style={STYLE} onClick={onRead} title={note.path}>
              <BookOpen size={14} /> Read detail
            </button>
          )}
          {note.unfiled && (
            <button type="button" className={BUTTON} style={STYLE} onClick={() => jobs.start('file-note')}
              title="Claude files the note in your vault, in the background, and says where">
              <FolderInput size={14} /> File it
            </button>
          )}
          {note.unfiled && (confirmingDelete ? (
            <>
              <button type="button" className="inline-flex items-center border border-red-500 px-2.5 py-1 text-red-500"
                style={STYLE} onClick={() => { jobs.deleteNote(); setConfirmingDelete(false) }}>
                Delete the note?
              </button>
              <button type="button" aria-label="Keep the note" className={BUTTON} style={STYLE}
                onClick={() => setConfirmingDelete(false)}>
                <X size={13} />
              </button>
            </>
          ) : (
            <button type="button" className={BUTTON} style={STYLE} onClick={() => setConfirmingDelete(true)}
              title="Move the note to the vault's trash; counts as not useful">
              <Trash2 size={14} /> Delete note
            </button>
          ))}
          {filed && (
            <span className="text-muted" style={{ fontSize: 'var(--font-size-actions)' }}>
              Filed in <span className="text-body">{folderOf(note.path!)}</span>
            </span>
          )}
          {filed && onMove && (
            <button type="button" className={BUTTON} style={STYLE} onClick={() => onMove(folderOf(note.path!))}
              title="Ask your linked Claude session to move it">
              Move
            </button>
          )}
        </div>
      )}
      {latest && latest.status === 'failed' && !isActive(latest) && (
        <div className="flex flex-wrap items-center gap-2 text-red-600" style={{ fontSize: 'var(--font-size-actions)' }}>
          <span role="alert">{failedLine(latest)}</span>
          {/* Only when trying again can work: no note yet to prepare, or a note still to file. */}
          {(latest.kind === 'prepare-detail' ? !note.path : note.unfiled) && (
            <button type="button" className={BUTTON} style={STYLE} onClick={() => jobs.start(latest.kind)}>
              <RotateCcw size={13} /> Try again
            </button>
          )}
        </div>
      )}
      {latest && latest.status === 'ok' && latest.message && (
        <div className="text-muted" style={{ fontSize: 'var(--font-size-actions)' }}>
          Claude: {latest.message}
        </div>
      )}
      {latest && !isActive(latest) && usageLine(latest) && (
        <div className="text-muted" style={{ fontSize: 'var(--font-size-meta)' }}>
          {usageLine(latest)}
        </div>
      )}
      {filed && lastFiling && lastFiling !== latest && lastFiling.message && (
        <div className="text-muted" style={{ fontSize: 'var(--font-size-actions)' }}>
          Claude: {lastFiling.message}
        </div>
      )}
      {error && (
        <div role="alert" className="text-red-600" style={{ fontSize: 'var(--font-size-actions)' }}>
          {error}
        </div>
      )}
    </div>
  )
}

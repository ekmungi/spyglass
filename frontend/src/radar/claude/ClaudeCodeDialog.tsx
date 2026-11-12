// ClaudeCodeDialog: "Open in Claude Code" for one item, to talk it through or to ask for something of
// your own. (Filing is the To file queue, not this dialog.) The dialog states what it does, offers two
// choices and shows, word for word, the text that will be sent. Spyglass itself never writes into the vault.
import { useId, useState } from 'react'
import { openInClaude } from '../api/client'
import { errorMessage, isMissing, NOT_AVAILABLE_YET } from '../api/errors'
import type { ClaudeIntent } from '../api/types'
import { Button, Dialog, toast } from '../ui'
import { closeClaudeDialog, startingIntent, type ClaudeDialogRequest } from './claudeStore'
import { buildClaudeRequest, INTENT_CHOICES } from './request'
import { useClaudePreview } from './useClaudePreview'
import './claude.css'

/** The toast shown once Claude Code has been asked to open. */
export const OPENED_TOAST = 'Claude Code is opening. Finish there; Spyglass shows where it was filed when Claude reports back.'

/** The dialog for one request; mount it only while open (each opening starts with fresh choices). */
export function ClaudeCodeDialog({ request }: { request: ClaudeDialogRequest }) {
  const [intent, setIntent] = useState<ClaudeIntent>(() => startingIntent(request))
  const [custom, setCustom] = useState('')
  const [opening, setOpening] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)
  const textId = useId()
  const customId = useId()

  const body = buildClaudeRequest({ intent, custom })
  const { preview, loading, problem } = useClaudePreview(request.itemId, body)

  const available = preview?.available !== false
  const needsText = intent === 'custom' && !custom.trim()
  const canOpen = !loading && !opening && !problem && preview !== null && available && !needsText
  const reason = preview && !available ? preview.reason || 'Claude Code cannot be opened from here right now.' : null

  const open = async () => {
    setOpening(true)
    setFailure(null)
    try {
      await openInClaude(request.itemId, body)
      toast(OPENED_TOAST)
      closeClaudeDialog()
    } catch (cause) {
      setFailure(isMissing(cause) ? NOT_AVAILABLE_YET : errorMessage(cause))
      setOpening(false)
    }
  }

  return (
    <Dialog
      open
      onClose={closeClaudeDialog}
      title="Open in Claude Code"
      footer={
        <>
          <Button variant="quiet" onClick={closeClaudeDialog}>
            Cancel
          </Button>
          <Button variant="primary" disabled={!canOpen} onClick={() => void open()}>
            {opening ? 'Opening…' : 'Open Claude Code'}
          </Button>
        </>
      }
    >
      <p className="rcc-lede">Claude Code opens in your notes vault with this item. You see and approve everything it does there.</p>

      <fieldset className="rcc-choices">
        <legend className="r-sr-only">What Claude Code should do with this item</legend>
        {INTENT_CHOICES.map((choice) => (
          <label key={choice.intent} className="rcc-choice">
            <input type="radio" name={`${textId}-intent`} checked={intent === choice.intent} onChange={() => setIntent(choice.intent)} />
            <span>
              <span className="rcc-choice__name">{choice.label}</span>
              <span className="rcc-choice__hint">{choice.hint}</span>
            </span>
          </label>
        ))}
      </fieldset>

      {intent === 'custom' && (
        <div className="r-field">
          <label htmlFor={customId}>Your request</label>
          <textarea
            id={customId}
            className="r-textarea"
            rows={3}
            value={custom}
            placeholder="For example: compare this with what I already know about report drafting"
            onChange={(event) => setCustom(event.target.value)}
          />
        </div>
      )}

      <div className="r-field rcc-sent">
        <label htmlFor={textId}>Exactly what will be sent</label>
        <textarea
          id={textId}
          className="r-textarea rcc-sent__text"
          readOnly
          rows={7}
          aria-busy={loading || undefined}
          data-stale={loading ? 'true' : undefined}
          value={preview?.text ?? ''}
          placeholder={loading ? 'Preparing…' : ''}
        />
        {preview?.vault && <span className="r-meta">Opens in {preview.vault}</span>}
      </div>

      {(problem || reason || failure) && (
        <p className="rcc-problem" role="alert">
          {problem || reason || failure}
        </p>
      )}
    </Dialog>
  )
}

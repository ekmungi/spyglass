// FileNowControl: the manual route, kept as a quiet secondary control in the To file view. File now
// opens ONE visible Claude Code session in the vault that proposes a table and waits for a yes; See
// the request shows that request word for word without opening anything.
import { useState } from 'react'
import { openFiling, previewFiling } from '../api/client'
import { errorMessage, isMissing, NOT_AVAILABLE_YET } from '../api/errors'
import type { ClaudePreview } from '../api/types'
import { OPENED_TOAST } from '../claude/ClaudeCodeDialog'
import { Button, toast } from '../ui'

/** File now and See the request; shown only while something waits. */
export function FileNowControl() {
  const [opening, setOpening] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)
  const [preview, setPreview] = useState<ClaudePreview | null>(null)
  const [seeing, setSeeing] = useState(false)

  const fileNow = async () => {
    setOpening(true)
    setFailure(null)
    try {
      await openFiling()
      toast(OPENED_TOAST)
    } catch (cause) {
      setFailure(isMissing(cause) ? NOT_AVAILABLE_YET : errorMessage(cause))
    } finally {
      setOpening(false)
    }
  }

  const seeRequest = async () => {
    if (seeing) {
      setSeeing(false)
      return
    }
    setFailure(null)
    try {
      setPreview(await previewFiling())
      setSeeing(true)
    } catch (cause) {
      setFailure(isMissing(cause) ? NOT_AVAILABLE_YET : errorMessage(cause))
    }
  }

  const unavailable = seeing && preview && !preview.available ? preview.reason || 'Claude Code cannot be opened from here right now.' : null
  const problem = failure ?? unavailable

  return (
    <div className="r-filing__manual">
      <div className="r-filing__manual-actions">
        <Button variant="quiet" size="sm" disabled={opening} onClick={() => void fileNow()} title="Open one Claude Code session in your vault that proposes where each item goes and waits for your yes">
          {opening ? 'Opening…' : 'File now'}
        </Button>
        <Button variant="quiet" size="sm" aria-expanded={seeing} onClick={() => void seeRequest()}>
          See the request
        </Button>
      </div>
      {seeing && preview && (
        <>
          <pre className="r-filing__request r-appear" aria-label="The request sent to Claude Code">
            {preview.text}
          </pre>
          {preview.vault && <span className="r-meta">Opens in {preview.vault}</span>}
        </>
      )}
      {problem && (
        <p className="r-filing__problem" role="alert">
          {problem}
        </p>
      )}
    </div>
  )
}

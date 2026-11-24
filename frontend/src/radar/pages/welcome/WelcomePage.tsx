// The first-start page: asks where Spyglass keeps its data and which Obsidian vault to use, waits
// while Spyglass restarts on a new folder, and then shows the browser extension guide.
import { useEffect, useId, useState, type FormEvent } from 'react'
import { saveFirstStart } from '../../api/client'
import { errorMessage } from '../../api/errors'
import type { FirstStart } from '../../api/types'
import { waitForService } from '../../api/waitForService'
import { Button, SectionHeading } from '../../ui'
import '../settings/settings.css'
import { BrowserGuide } from './BrowserGuide'
import './welcome.css'

type Phase = 'data' | 'restarting' | 'stalled' | 'guide'

interface WelcomePageProps {
  /** What the service said about this start; the page only shows the parts that apply. */
  firstStart: FirstStart
  /** Called when the page has nothing more to ask, so the app shows its normal page. */
  onDone: () => void
  /** Reload the page once the service is back; a prop so tests can watch it. */
  reload?: () => void
}

/** The page shown in place of the app on a first start, and for a browser guide that is still waiting. */
export function WelcomePage({ firstStart, onDone, reload = () => window.location.reload() }: WelcomePageProps) {
  const [phase, setPhase] = useState<Phase>(firstStart.needed ? 'data' : 'guide')
  const [dataDir, setDataDir] = useState(firstStart.data_dir)
  const [vaultPath, setVaultPath] = useState(firstStart.vault_path ?? '')
  const [saving, setSaving] = useState(false)
  const [refusal, setRefusal] = useState<string | null>(null)
  const folderId = useId()
  const vaultId = useId()

  // After a restart is announced, wait for the new Spyglass on the same port, then reload so the page
  // comes from it. The old service still answers for a moment, so one missed answer is waited for first.
  useEffect(() => {
    if (phase !== 'restarting') return
    let cancelled = false
    void waitForService({ afterStop: true }).then((answered) => {
      if (cancelled) return
      if (answered) reload()
      else setPhase('stalled')
    })
    return () => {
      cancelled = true
    }
    // reload is a prop that may change identity on each render; the wait must start once per restart.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase])

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setSaving(true)
    setRefusal(null)
    try {
      const saved = await saveFirstStart({ data_dir: dataDir.trim(), vault_path: vaultPath.trim() || null })
      if (saved.restart) setPhase('restarting')
      else if (firstStart.browsers.length > 0) setPhase('guide')
      else onDone()
    } catch (cause) {
      setRefusal(errorMessage(cause))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="rw-screen">
      <div className="r-page">
        <h1 className="r-page-title">Welcome to Spyglass</h1>
        {phase === 'data' && (
          <form onSubmit={(event) => void submit(event)} className="rst-section">
            <SectionHeading>Where Spyglass keeps your things</SectionHeading>
            <div className="r-field">
              <label htmlFor={folderId}>Data folder</label>
              <input id={folderId} className="r-input" value={dataDir} onChange={(event) => setDataDir(event.target.value)} spellCheck={false} />
            </div>
            <p className="r-meta">
              Spyglass keeps its database, logs and backups in this folder. The folder stays when Spyglass is uninstalled, so your collection is not
              lost. The suggested folder is fine for most people.
            </p>
            <div className="r-field">
              <label htmlFor={vaultId}>Obsidian vault (optional)</label>
              <input id={vaultId} className="r-input" value={vaultPath} onChange={(event) => setVaultPath(event.target.value)} spellCheck={false} />
            </div>
            <p className="r-meta">Leave this empty if you do not use Obsidian. You can set or change it later in Settings.</p>
            <div className="rst-actions">
              <Button type="submit" variant="primary" disabled={saving}>
                Save and continue
              </Button>
              {refusal && (
                <span className="r-error-text" role="alert">
                  {refusal}
                </span>
              )}
            </div>
          </form>
        )}
        {phase === 'restarting' && (
          <p className="r-meta" role="status">
            Spyglass is starting again on the new folder. This page reloads when it is ready.
          </p>
        )}
        {phase === 'stalled' && (
          <p className="r-error-text" role="alert">
            Spyglass did not start again within a minute. Open Spyglass from the Start menu, then reload this page.
          </p>
        )}
        {phase === 'guide' && <BrowserGuide browsers={firstStart.browsers} onDone={onDone} />}
      </div>
    </div>
  )
}

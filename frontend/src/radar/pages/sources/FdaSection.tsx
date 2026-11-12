// FdaSection: the FDA device decisions source. Two sentences on what it does, an on/off switch,
// the optional product codes and keywords, and the last run in words.
import { useEffect, useId, useState, type FormEvent } from 'react'
import { errorMessage } from '../../api/errors'
import { Button, SectionHeading } from '../../ui'
import type { CollectorRow } from './api'
import { collectorStatus, newItemsText } from './describe'
import { listProblem, loadFdaSettings, saveFdaSettings, type FdaSettings } from './fdaApi'
import { formatWhen } from './format'
import { Switch } from './Switch'

export interface FdaSectionProps {
  collectors: readonly CollectorRow[]
}

/** The "FDA device decisions" group of the Sources page. */
export function FdaSection({ collectors }: FdaSectionProps) {
  const [settings, setSettings] = useState<FdaSettings | null>(null)
  const [codes, setCodes] = useState('')
  const [words, setWords] = useState('')
  const [note, setNote] = useState<{ text: string; failed: boolean } | null>(null)
  const [busy, setBusy] = useState(false)
  const codesId = useId()
  const wordsId = useId()

  useEffect(() => {
    let live = true
    loadFdaSettings()
      .then((loaded) => {
        if (!live) return
        setSettings(loaded)
        setCodes(loaded.productCodes)
        setWords(loaded.keywords)
      })
      .catch((cause) => {
        if (live) setNote({ text: `The FDA settings could not be read. ${errorMessage(cause)}`, failed: true })
      })
    return () => {
      live = false
    }
  }, [])

  const row = collectors.find((c) => c.key === 'fda')
  const status = row ? collectorStatus(row) : null
  const found = row?.status === 'ok' ? newItemsText(row.newItems) : ''

  const toggle = async (enabled: boolean) => {
    if (!settings) return
    setNote(null)
    try {
      setSettings(await saveFdaSettings({ enabled }))
    } catch (cause) {
      setNote({ text: errorMessage(cause), failed: true })
    }
  }

  const save = async (event: FormEvent) => {
    event.preventDefault()
    const problem = listProblem({ productCodes: codes, keywords: words })
    if (problem) {
      setNote({ text: problem, failed: true })
      return
    }
    setBusy(true)
    setNote(null)
    try {
      const saved = await saveFdaSettings({ productCodes: codes.trim(), keywords: words.trim() })
      setSettings(saved)
      setNote({ text: 'Saved. The lists are used at the next daily check.', failed: false })
    } catch (cause) {
      setNote({ text: errorMessage(cause), failed: true })
    } finally {
      setBusy(false)
    }
  }

  const unchanged = !settings || (codes.trim() === settings.productCodes && words.trim() === settings.keywords)

  return (
    <section aria-labelledby="sources-fda" className="rs-section">
      <SectionHeading id="sources-fda">FDA device decisions</SectionHeading>
      <div className="rs-row">
        <div className="rs-main">
          <div className="rs-line">
            <span className="rs-name">Clearances, approvals and recalls</span>
            {status && (
              <span className={status.tone === 'problem' ? 'rs-problem' : status.tone === 'ok' ? 'rs-ok' : 'r-meta'}>
                {status.tone === 'problem' ? 'Failing' : status.text}
              </span>
            )}
          </div>
          <p className="rs-sub">
            Once a day Spyglass asks the public FDA database (openFDA) for new 510(k) clearances, De Novo grants, PMA approvals and
            recalls from the companies on your watch list, and adds each as an item from the regulator. Only the company names and the
            lists below are sent, to api.fda.gov, with no key or account.
          </p>
          {status?.tone === 'problem' && <p className="rs-problem">{status.text}</p>}
          {row?.lastRun && <p className="r-meta">{[`Last run ${formatWhen(row.lastRun)}`, found].filter(Boolean).join(' · ')}</p>}
        </div>
        <div className="rs-actions">
          <Switch label="FDA device decisions on or off" checked={settings?.enabled ?? true} disabled={!settings} onChange={toggle} />
        </div>
      </div>
      <form onSubmit={save} noValidate className="rs-form">
        <label htmlFor={codesId} className="rs-name">
          Product codes
        </label>
        <p className="rs-sub">Optional. Three-character FDA product codes to follow whoever makes them, separated by commas.</p>
        <input id={codesId} className="r-input" value={codes} placeholder="QAS, NAY" disabled={!settings} onChange={(e) => setCodes(e.target.value)} />
        <label htmlFor={wordsId} className="rs-name rs-form__gap">
          Device keywords
        </label>
        <p className="rs-sub">Optional. Words in a device name to follow, separated by commas.</p>
        <div className="rs-form__row">
          <input id={wordsId} className="r-input" value={words} placeholder="infusion pump, ultrasound" disabled={!settings} onChange={(e) => setWords(e.target.value)} />
          <Button type="submit" variant="secondary" disabled={busy || unchanged}>
            Save lists
          </Button>
        </div>
        <p className="rs-form__note" role="status" aria-live="polite">
          {note && <span className={note.failed ? 'r-error-text' : 'r-meta'}>{note.text}</span>}
        </p>
      </form>
    </section>
  )
}

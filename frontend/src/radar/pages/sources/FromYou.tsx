// FromYou: the ways a link gets into Spyglass (Slack, Raindrop, Gmail, the Add link box), each
// shown as set up or not, with one line on what to do when it is not.
import { useId, useState, type FormEvent } from 'react'
import { errorMessage } from '../../api/errors'
import { Button, SectionHeading } from '../../ui'
import { captureLink, type CollectorRow } from './api'
import { collectorStatus, isNotConfigured } from './describe'
import { formatWhen } from './format'

interface Channel {
  id: string
  /** Collector keys that report on this channel, in order of preference. */
  keys: string[]
  name: string
  how: string
  /** What the channel needs, in a few words (shown before the pointer to the settings file). */
  needs: string
}

const CHANNELS: Channel[] = [
  {
    id: 'slack',
    keys: ['slack'],
    name: 'Slack channel',
    how: 'Post a link in your Spyglass channel and it appears under From you.',
    needs: 'Slack needs a bot token and the channel to read.',
  },
  {
    id: 'raindrop',
    keys: ['raindrop'],
    name: 'Raindrop',
    how: 'Bookmark a page in Raindrop and it arrives here.',
    needs: 'Raindrop needs your access token.',
  },
  {
    id: 'gmail',
    keys: ['gmail', 'newsletter'],
    name: 'Gmail label',
    how: 'Mail yourself a link under the label Spyglass, or label newsletters Newsletters.',
    needs: 'Gmail needs your address and an app password.',
  },
]

export interface FromYouProps {
  collectors: readonly CollectorRow[]
}

/** The "From you" group. The Add link row works at once; the other three report their setup state. */
export function FromYou({ collectors }: FromYouProps) {
  return (
    <section aria-labelledby="sources-from-you" className="rs-section">
      <SectionHeading id="sources-from-you">From you</SectionHeading>
      <ul className="r-rows">
        {CHANNELS.map((channel) => (
          <ChannelRow key={channel.id} channel={channel} row={channel.keys.map((key) => collectors.find((c) => c.key === key)).find(Boolean)} />
        ))}
        <li className="rs-row rs-row--stack">
          <AddLink />
        </li>
      </ul>
    </section>
  )
}

function ChannelRow({ channel, row }: { channel: Channel; row: CollectorRow | undefined }) {
  const notSet = isNotConfigured(row)
  const status = row && !notSet ? collectorStatus(row) : null
  const waiting = row?.status === 'never' && !notSet
  const label = notSet ? 'Not configured' : waiting ? 'Waiting for its first run' : status?.tone === 'problem' ? 'Set up, but failing' : 'Configured'
  return (
    <li className="rs-row">
      <div className="rs-main">
        <div className="rs-line">
          <span className="rs-name">{channel.name}</span>
          <span className={notSet ? 'r-meta' : status?.tone === 'problem' ? 'rs-problem' : 'rs-ok'}>{label}</span>
        </div>
        <p className="rs-sub">{channel.how}</p>
        {notSet && (
          <p className="r-meta">
            {channel.needs} This is set once in Spyglass&rsquo;s settings file; see the <a href="#/settings">setup guide</a>.
          </p>
        )}
        {status?.tone === 'problem' && <p className="rs-problem">{status.text}</p>}
        {row?.lastRun && !notSet && <p className="r-meta">Last checked {formatWhen(row.lastRun)}</p>}
      </div>
    </li>
  )
}

/** A one-line form that sends a link in now. */
function AddLink() {
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<{ text: string; failed: boolean } | null>(null)
  const inputId = useId()

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const text = url.trim()
    if (!/^https?:\/\//i.test(text)) {
      setNote({ text: 'Enter a full web address starting with http:// or https://.', failed: true })
      return
    }
    setBusy(true)
    setNote(null)
    try {
      await captureLink({ url: text })
      setUrl('')
      setNote({ text: 'Added. It appears under From you in your feed.', failed: false })
    } catch (cause) {
      setNote({ text: errorMessage(cause), failed: true })
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} noValidate className="rs-form">
      <div className="rs-line">
        <label htmlFor={inputId} className="rs-name">
          Add a link
        </label>
        <span className="rs-ok">Always available</span>
      </div>
      <p className="rs-sub">Paste any web address to send it in right now.</p>
      <div className="rs-form__row">
        <input id={inputId} className="r-input" value={url} placeholder="https://" onChange={(event) => setUrl(event.target.value)} />
        <Button type="submit" variant="secondary" disabled={busy || !url.trim()}>
          Add link
        </Button>
      </div>
      <p className="rs-form__note" role="status" aria-live="polite">
        {note && <span className={note.failed ? 'r-error-text' : 'r-meta'}>{note.text}</span>}
      </p>
    </form>
  )
}

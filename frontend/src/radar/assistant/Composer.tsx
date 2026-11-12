// Composer: the quoted passage (if any), the text box and Send / Stop. Enter sends; Shift+Enter
// adds a line.
import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { IconButton, IconClose, IconSend, IconStop } from '../ui'
import { maxComposerHeight } from './composerHeight'

export interface ComposerProps {
  placeholder: string
  quote: string | null
  onClearQuote: () => void
  streaming: boolean
  disabled: boolean
  focusToken: number
  onSend: (text: string) => void
  onStop: () => void
}

// The last focus request already honoured. Module-level so that a panel which mounts later (for
// example when an article opens) does not steal focus for an old request.
let consumedFocusToken = 0

/** The message box at the bottom of the assistant panel. */
export function Composer({ placeholder, quote, onClearQuote, streaming, disabled, focusToken, onSend, onStop }: ComposerProps) {
  const [text, setText] = useState('')
  const areaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (focusToken > consumedFocusToken) {
      consumedFocusToken = focusToken
      areaRef.current?.focus()
    }
  }, [focusToken])

  // Grow with the text up to six lines, then scroll.
  useEffect(() => {
    const area = areaRef.current
    if (!area) return
    area.style.height = 'auto'
    area.style.height = `${Math.min(area.scrollHeight, maxComposerHeight(getComputedStyle(area)))}px`
  }, [text])

  const submit = () => {
    const value = text.trim()
    if (!value || streaming || disabled) return
    onSend(value)
    setText('')
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <div className="r-composer">
      {quote && (
        <div className="r-composer__quote">
          <span className="r-composer__quote-text">&ldquo;{quote.length > 160 ? `${quote.slice(0, 159)}…` : quote}&rdquo;</span>
          <IconButton size="sm" label="Remove quote" icon={<IconClose size={14} />} onClick={onClearQuote} />
        </div>
      )}
      <div className="r-composer__box">
        <label className="r-sr-only" htmlFor="r-composer-input">
          Message the assistant
        </label>
        <textarea
          id="r-composer-input"
          ref={areaRef}
          rows={1}
          value={text}
          placeholder={quote ? 'Ask about this passage' : placeholder}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={onKeyDown}
          disabled={disabled}
        />
        {streaming ? (
          <IconButton label="Stop" icon={<IconStop size={14} fill="currentColor" />} onClick={onStop} className="r-composer__stop" tooltipSide="top" />
        ) : (
          <IconButton label="Send" icon={<IconSend size={16} />} onClick={submit} disabled={!text.trim() || disabled} className="r-composer__send" tooltipSide="top" />
        )}
      </div>
    </div>
  )
}

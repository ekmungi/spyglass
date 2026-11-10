// Shown when Spyglass could not open the Claude desktop app: copies the
// prompt so the user can paste it into a new Claude session themselves.
import { useState } from 'react'

interface Props {
  prompt: string
  /** Called a moment after a successful copy, so the button can go away. */
  onDone: () => void
}

export function CopyPromptButton({ prompt, onDone }: Props) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle')

  const copy = () => {
    navigator.clipboard
      .writeText(prompt)
      .then(() => {
        setState('copied')
        setTimeout(onDone, 1500)
      })
      .catch(() => setState('failed'))
  }

  const label = state === 'copied' ? 'Copied' : state === 'failed' ? 'Copy failed' : 'Copy prompt'
  return (
    <button
      type="button"
      className="text-accent hover:underline"
      style={{ fontSize: 'var(--font-size-meta)' }}
      onClick={copy}
    >
      {label}
    </button>
  )
}

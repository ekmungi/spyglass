// EmptyState: what an empty or unavailable screen says, and the one thing to do next.
import type { ReactNode } from 'react'

export interface EmptyStateProps {
  title: string
  body?: ReactNode
  action?: ReactNode
}

/** A serif title, one plain sentence of direction and an optional action (usually a Button). */
export function EmptyState({ title, body, action }: EmptyStateProps) {
  return (
    <section className="r-empty">
      <h2 className="r-empty__title">{title}</h2>
      {body && <p className="r-empty__body">{body}</p>}
      {action}
    </section>
  )
}

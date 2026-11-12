// SectionHeading: the small-caps heading that opens each section, set over a hairline.
import type { ReactNode } from 'react'

export interface SectionHeadingProps {
  children: ReactNode
  note?: ReactNode
  id?: string
  as?: 'h2' | 'h3'
}

/** A small-caps section title with an optional quiet note on the right ("3 picked from 96"). */
export function SectionHeading({ children, note, id, as = 'h2' }: SectionHeadingProps) {
  const Tag = as
  return (
    <div className="r-section-heading">
      <Tag className="r-section-heading__title" id={id}>
        {children}
      </Tag>
      {note && <span className="r-section-heading__note">{note}</span>}
    </div>
  )
}

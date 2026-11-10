// Interactive brief narrative: renders the parsed overview + theme sections from
// briefBullets.ts. Each bullet has a left grip-select gutter (selection state lives in
// BriefReader) and, when it has related items, a right-edge chevron that toggles a
// collapsible "Related:" sub-line at the bottom of the bullet (the related
// line is hidden until the chevron reveals it).
import { ChevronDown, ChevronUp } from 'lucide-react'
import { useState } from 'react'
import { bulletKey, type Bullet, type ParsedBrief } from '../lib/briefBullets'
import { Markdown } from './workspace/Markdown'

interface Props {
  parsed: ParsedBrief
  selected: Set<string>
  onToggleBullet: (key: string) => void
  onCardLink?: (id: number) => void
}

// Shared markdown styling, matching BriefReader's narrative/panel style.
const MD_STYLE = { fontSize: 'var(--font-size-body)', lineHeight: 1.6 } as const

/** One bullet row: grip gutter, markdown body, a collapsible related sub-line, and a
 * right-edge chevron that toggles it. The related line starts collapsed and expands at
 * the bottom of the bullet, revealed on demand. */
function BulletRow({
  bullet,
  bulletKey: key,
  isSelected,
  onToggleBullet,
  onCardLink,
}: {
  bullet: Bullet
  bulletKey: string
  isSelected: boolean
  onToggleBullet: (key: string) => void
  onCardLink?: (id: number) => void
}) {
  const hasRelated = bullet.related.length > 0
  // Per-bullet expand state: the related sub-line is hidden until the chevron reveals it.
  const [showRelated, setShowRelated] = useState(false)
  return (
    <div className="brief-bullet-row flex items-start gap-2">
      {/* 28px left gutter; the button IS the full hit zone (full gutter width + full
          bullet height, transparent), wrapping a slim coral rule for hover/selected. */}
      <div className="brief-bullet-gutter flex w-[28px] shrink-0 items-stretch justify-center self-stretch">
        <button
          type="button"
          aria-label="Select this bullet"
          title="Select this bullet"
          aria-pressed={isSelected}
          className={`brief-bullet-grip${isSelected ? ' is-selected' : ''}`}
          onClick={() => onToggleBullet(key)}
        >
          <span aria-hidden="true" className="brief-bullet-grip-bar" />
        </button>
      </div>
      <div className="min-w-0 flex-1">
        <Markdown className="text-body" style={MD_STYLE} onCardLink={onCardLink}>
          {bullet.markdown}
        </Markdown>
        {/* Collapsible related sub-line: revealed by the chevron, extends the bullet
            downward. Each item routes to the workspace reader like an inline card link. */}
        {hasRelated && showRelated && (
          <div className="brief-bullet-related mt-2" style={{ fontSize: 'var(--font-size-meta)' }}>
            <span className="text-muted">Related: </span>
            {bullet.related.map((related, index) => (
              <span key={related.id}>
                <button
                  type="button"
                  className="text-accent hover:underline"
                  onClick={() => onCardLink?.(related.id)}
                >
                  {related.title}
                </button>
                {index < bullet.related.length - 1 && <span className="text-muted">, </span>}
              </span>
            ))}
          </div>
        )}
      </div>
      {/* Right-edge chevron: toggles the related sub-line. Only shown when the bullet
          has related items; a fixed-size control so it never reflows the bullet text. */}
      {hasRelated && (
        <button
          type="button"
          aria-label={showRelated ? 'Hide related items' : 'Show related items'}
          title={showRelated ? 'Hide related' : `Show ${bullet.related.length} related`}
          aria-expanded={showRelated}
          className="brief-bullet-related-toggle flex size-[26px] shrink-0 items-center justify-center border border-border text-muted hover:border-accent hover:text-accent"
          style={{ borderRadius: 'var(--radius-control)' }}
          onClick={() => setShowRelated((value) => !value)}
        >
          {showRelated ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
        </button>
      )}
    </div>
  )
}

/** Interactive narrative: overview + theme sections, each bullet grip-selectable with
 * an on-demand related sub-line. Selection state and the Claude launch control live in
 * the parent (BriefReader); this component renders structure and forwards callbacks. */
export function BriefNarrative({ parsed, selected, onToggleBullet, onCardLink }: Props) {
  return (
    <div>
      {parsed.overview && (
        <Markdown className="text-body" style={MD_STYLE} onCardLink={onCardLink}>
          {parsed.overview}
        </Markdown>
      )}
      {parsed.sections.map((section, sectionIndex) => (
        <div key={sectionIndex} className="mt-4">
          <h3 className="mb-2 font-bold text-ink" style={{ fontSize: 'var(--font-size-body)' }}>
            {section.heading}
          </h3>
          <div className="flex flex-col gap-2">
            {section.bullets.map((bullet, bulletIndex) => {
              const key = bulletKey(sectionIndex, bulletIndex)
              return (
                <BulletRow
                  key={key}
                  bullet={bullet}
                  bulletKey={key}
                  isSelected={selected.has(key)}
                  onToggleBullet={onToggleBullet}
                  onCardLink={onCardLink}
                />
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}

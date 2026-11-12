// StoryRow: one story in the brief, drawn according to its section (top, watch, notable, papers,
// from you, skim). The headline is the single click target; save appears on hover.
import { useState } from 'react'
import type { BriefSectionKey, Story } from '../api/types'
import { ItemLink } from '../components/ItemLink'
import { SaveButton } from '../components/SaveButton'
import { sentByYou, sourcesLine, watchLabel } from '../lib/format'
import { plainText } from '../lib/plainText'
import { useItemState } from '../state/itemState'
import { IconButton, IconExpand } from '../ui'

export interface StoryRowProps {
  story: Story
  section: BriefSectionKey
  index: number
  selected: boolean
}

/** Join the non-empty parts of a meta line with a middle dot. */
function Meta({ parts }: { parts: (string | null | undefined)[] }) {
  const shown = parts.filter((part): part is string => Boolean(part))
  if (!shown.length) return null
  return <p className="r-story__meta">{shown.join(' · ')}</p>
}

/** A story drawn for its brief section. */
export function StoryRow({ story, section, index, selected }: StoryRowProps) {
  const state = useItemState(story.item_id, story.state)
  const [expanded, setExpanded] = useState(false)
  const classes = ['r-story', `r-story--${section}`, state.opened ? 'is-read' : '', selected ? 'is-selected' : '', state.saved ? 'is-saved' : '']
    .filter(Boolean)
    .join(' ')
  const sources = sourcesLine(story.sources, story.source_count)
  const headline = plainText(story.headline)

  if (section === 'skim') {
    return (
      <li className={classes} data-row-index={index}>
        <ItemLink id={story.item_id} className="r-story__link" title={story.why ?? undefined}>
          <span className="r-story__headline">{headline}</span>
          <span className="r-story__origin">{story.sources[0]?.name}</span>
        </ItemLink>
        <SaveButton id={story.item_id} base={story.state} />
      </li>
    )
  }

  if (section === 'notable') {
    const open = expanded || selected
    return (
      <li className={classes} data-row-index={index}>
        <div className="r-story__line">
          <ItemLink id={story.item_id} className="r-story__link" title={open ? undefined : story.why ?? undefined}>
            <span className="r-story__headline">{headline}</span>
          </ItemLink>
          <span className="r-story__label">{story.section_label}</span>
          {story.why && (
            <IconButton
              size="sm"
              className={`r-story__expand${open ? ' is-open' : ''}`}
              label={open ? 'Hide why it matters' : 'Why it matters'}
              aria-expanded={open}
              icon={<IconExpand size={16} />}
              onClick={() => setExpanded((value) => !value)}
            />
          )}
          <SaveButton id={story.item_id} base={story.state} />
        </div>
        {open && story.why && <p className="r-story__why">{story.why}</p>}
      </li>
    )
  }

  // Only watch rows say which watched organisation the story is about.
  const watched = section === 'watch' ? watchLabel(story.watch) : null
  const meta =
    section === 'papers'
      ? [story.signal, story.section_label]
      : section === 'from_you'
        ? [story.sources[0]?.name, story.section_label]
        : [sources, story.section_label, story.signal]

  return (
    <li className={classes} data-row-index={index}>
      {section === 'from_you' && <p className="r-story__sent">{sentByYou(state.captured_via)}</p>}
      <div className="r-story__line">
        <ItemLink id={story.item_id} className="r-story__link">
          <span className="r-story__headline">{headline}</span>
        </ItemLink>
        <SaveButton id={story.item_id} base={story.state} />
      </div>
      {story.why && <p className="r-story__why">{story.why}</p>}
      {watched && <p className="r-story__watch">{watched}</p>}
      <Meta parts={meta} />
    </li>
  )
}

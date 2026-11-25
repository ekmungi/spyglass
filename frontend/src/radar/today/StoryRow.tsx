// StoryRow: one story in the brief, drawn according to its section (top, watch, notable, papers,
// from you, skim). The headline is the single click target; the thumbs and Save appear on hover. A
// story that was judged and not picked carries a grey ring before its headline.
import { useState } from 'react'
import type { BriefSectionKey, Story } from '../api/types'
import { ItemLink } from '../components/ItemLink'
import { SaveButton } from '../components/SaveButton'
import { VoteButtons } from '../components/VoteButtons'
import { sentByYou, sourcesLine, watchLabel } from '../lib/format'
import { plainText } from '../lib/plainText'
import { useItemState } from '../state/itemState'
import { IconButton, IconExpand } from '../ui'

/** Tooltip and accessible text of the ring on an unpicked story. */
const RING_TIP = 'Not picked for today. Thumbs up tells Spyglass that it should have been.'

export interface StoryRowProps {
  story: Story
  section: BriefSectionKey
  index: number
  selected: boolean
  /** True for a story judged for the section and left out of the selection; it carries the ring. */
  unpicked?: boolean
}

/** Join the non-empty parts of a meta line with a middle dot. */
function Meta({ parts }: { parts: (string | null | undefined)[] }) {
  const shown = parts.filter((part): part is string => Boolean(part))
  if (!shown.length) return null
  return <p className="r-story__meta">{shown.join(' · ')}</p>
}

/**
 * The headline text, with the ring before it on an unpicked story. The ring sits inside the headline
 * so it stays on the first line; its tip is the native title, because the headline clips its overflow
 * (it stops long titles at four lines) and would cut off a drawn bubble.
 */
function Headline({ text, unpicked }: { text: string; unpicked: boolean }) {
  return (
    <span className="r-story__headline">
      {unpicked && <span className="r-story__ring" role="img" aria-label={RING_TIP} title={RING_TIP} />}
      {text}
    </span>
  )
}

/**
 * The story's text: two labelled paragraphs, "What it says" and "Why it matters", when the story has
 * the first; otherwise its one older text without a label. Nothing when the story has no text.
 */
function StoryText({ story }: { story: Story }) {
  if (!story.what) return story.why ? <p className="r-story__why">{story.why}</p> : null
  return (
    <div className="r-story__parts">
      <p className="r-story__why">
        <span className="r-story__part">What it says</span>
        {story.what}
      </p>
      {story.why && (
        <p className="r-story__why">
          <span className="r-story__part">Why it matters</span>
          {story.why}
        </p>
      )}
    </div>
  )
}

/** The thumbs and Save at the end of a row; the thumbs show on hover, on focus, or once a vote is set. */
function RowActions({ story }: { story: Story }) {
  return (
    <>
      <VoteButtons itemId={story.item_id} vote={story.state.vote} />
      <SaveButton id={story.item_id} base={story.state} />
    </>
  )
}

/** A story drawn for its brief section. */
export function StoryRow({ story, section, index, selected, unpicked = false }: StoryRowProps) {
  const state = useItemState(story.item_id, story.state)
  const [expanded, setExpanded] = useState(false)
  const classes = ['r-story', `r-story--${section}`, state.opened ? 'is-read' : '', selected ? 'is-selected' : '', state.saved ? 'is-saved' : '']
    .filter(Boolean)
    .join(' ')
  const sources = sourcesLine(story.sources, story.source_count)
  const headline = plainText(story.headline)
  // The hover text of a compact row: the older text, or "what it says" for a story that only has that.
  const hint = story.why || story.what || undefined

  if (section === 'skim') {
    return (
      <li className={classes} data-row-index={index}>
        <ItemLink id={story.item_id} className="r-story__link" title={hint}>
          <Headline text={headline} unpicked={unpicked} />
          <span className="r-story__origin">{story.sources[0]?.name}</span>
        </ItemLink>
        <RowActions story={story} />
      </li>
    )
  }

  if (section === 'notable') {
    const open = expanded || selected
    return (
      <li className={classes} data-row-index={index}>
        <div className="r-story__line">
          <ItemLink id={story.item_id} className="r-story__link" title={open ? undefined : hint}>
            <Headline text={headline} unpicked={unpicked} />
          </ItemLink>
          <span className="r-story__label">{story.section_label}</span>
          {hint && (
            <IconButton
              size="sm"
              className={`r-story__expand${open ? ' is-open' : ''}`}
              label={open ? 'Hide why it matters' : 'Why it matters'}
              aria-expanded={open}
              icon={<IconExpand size={16} />}
              onClick={() => setExpanded((value) => !value)}
            />
          )}
          <RowActions story={story} />
        </div>
        {open && <StoryText story={story} />}
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
          <Headline text={headline} unpicked={unpicked} />
        </ItemLink>
        <RowActions story={story} />
      </div>
      <StoryText story={story} />
      {watched && <p className="r-story__watch">{watched}</p>}
      <Meta parts={meta} />
    </li>
  )
}

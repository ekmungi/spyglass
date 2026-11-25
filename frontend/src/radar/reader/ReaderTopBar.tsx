// ReaderTopBar: the reader's bar of icon buttons, from left to right: Back; previous and next story
// with the count; the thumbs; Save; File in vault; the chat icon; open the original page; copy the
// link; the other sources; narrower and wider text (and a paper's PDF/Text switch); and More with
// "Open in Claude Code…", "Follow topics from this article" and "Show related in the Feed".
// Back and the walk through the list are there before the item has loaded and when it fails to open.
// Every tooltip opens downwards, because the bar sits at the top of the window.
import { useState } from 'react'
import type { ItemDetail } from '../api/types'
import { TEXT_WIDTH } from '../appearance/catalog'
import { setAssistOpen, useAssistState } from '../assistant/assistStore'
import { openClaudeDialog } from '../claude/claudeStore'
import { SaveButton } from '../components/SaveButton'
import { VoteButtons } from '../components/VoteButtons'
import { FileButton } from '../filing/FileButton'
import { FollowDialog } from '../follow/FollowDialog'
import { useAppearance } from '../hooks/useAppearance'
import { openExternal, safeHttpUrl } from '../lib/safeUrl'
import { goBack, navigate } from '../router'
import { useFilingConfigured } from '../state/filingConfigured'
import { useItemState } from '../state/itemState'
import { Button, IconAdd, IconAsk, IconBack, IconButton, IconMore, IconOpenOriginal, IconOtherSources, IconRemove, Menu, type MenuItem } from '../ui'
import { CopyLinkButton } from './CopyLinkButton'
import { ReadingNav } from './ReadingNav'

export interface ReaderTopBarProps {
  detail: ItemDetail
  showPdf: boolean
  onTogglePdf: () => void
}

/** A thin upright rule between groups of buttons. */
function Separator() {
  return <span className="r-readerbar__sep" aria-hidden="true" />
}

/** The outlets other than this item's that reported the same story. */
function otherSources(detail: ItemDetail): ItemDetail['story_sources'] {
  return detail.story_sources.filter((source) => source.item_id !== detail.id)
}

/** The other sources of the story, as an icon button whose menu opens one in place of this item. */
function OtherSources({ detail }: { detail: ItemDetail }) {
  const sourceItems: MenuItem[] = [
    { id: `self-${detail.id}`, label: detail.origin, checked: true, onSelect: () => undefined },
    ...otherSources(detail).map((source) => ({
      id: String(source.item_id),
      label: source.name,
      onSelect: () => navigate({ name: 'item', id: source.item_id }, { replace: true }),
    })),
  ]
  return (
    <Menu
      label="Other sources for this story"
      items={sourceItems}
      trigger={<IconButton label={`${sourceItems.length} sources for this story`} icon={<IconOtherSources size={18} />} tooltipSide="bottom" />}
    />
  )
}

/** "Narrower text" and "Wider text": one quick step of the stored text width each, disabled at the limits. */
function WidthButtons() {
  const { appearance, stepWidth } = useAppearance()
  return (
    <>
      <IconButton
        label="Narrower text"
        icon={<IconRemove size={18} />}
        tooltipSide="bottom"
        disabled={appearance.textWidth <= TEXT_WIDTH.min}
        onClick={() => stepWidth(-TEXT_WIDTH.quickStep)}
      />
      <IconButton
        label="Wider text"
        icon={<IconAdd size={18} />}
        tooltipSide="bottom"
        disabled={appearance.textWidth >= TEXT_WIDTH.max}
        onClick={() => stepWidth(TEXT_WIDTH.quickStep)}
      />
    </>
  )
}

/** The left end of the bar: Back, then previous and next story with the count. It needs only the item's id. */
function BarStart({ id }: { id: number }) {
  return (
    <div className="r-readerbar__left">
      <IconButton label="Back" icon={<IconBack size={18} />} onClick={() => goBack()} tooltipSide="bottom" />
      <ReadingNav id={id} />
    </div>
  )
}

export interface ReaderBarProps extends Omit<ReaderTopBarProps, 'detail'> {
  /** The id of the item the reader is for, known before the item has loaded. */
  id: number
  /** The item once it has loaded; undefined while it loads or when it could not be opened. */
  detail: ItemDetail | undefined
}

/**
 * The reader's bar for item `id`. Back, previous and next story and the count need only the id, so they
 * are there while the item loads and when it fails to open, in the place they keep once it is shown; the
 * item's own buttons join them when it has loaded. The page renders this one bar in every state, so a
 * focused button stays focused when the item arrives.
 */
export function ReaderBar({ id, detail, showPdf, onTogglePdf }: ReaderBarProps) {
  return (
    <div className="r-readerbar">
      <BarStart id={id} />
      {detail && <BarActions detail={detail} showPdf={showPdf} onTogglePdf={onTogglePdf} />}
    </div>
  )
}

/** The sticky bar at the top of the reader, for an item that has loaded. */
export function ReaderTopBar({ detail, showPdf, onTogglePdf }: ReaderTopBarProps) {
  return <ReaderBar id={detail.id} detail={detail} showPdf={showPdf} onTogglePdf={onTogglePdf} />
}

/** The item's own buttons: the thumbs, Save, File, the chat icon, the original, the sources, width and More. */
function BarActions({ detail, showPdf, onTogglePdf }: ReaderTopBarProps) {
  const state = useItemState(detail.id, detail.state)
  const assist = useAssistState()
  // The File in vault control exists only where the reader has set filing up.
  const filingOn = useFilingConfigured()
  const [following, setFollowing] = useState(false)
  const isPaper = detail.reader?.kind === 'paper' && detail.reader.status === 'ok'

  // Only a plain web address is ever opened or copied as "the original".
  const original = safeHttpUrl(detail.url)
  const hasOtherSources = otherSources(detail).length > 0
  const moreItems: MenuItem[] = [
    { id: 'claude', label: 'Open in Claude Code…', onSelect: () => openClaudeDialog({ itemId: detail.id }) },
    { id: 'follow', label: 'Follow topics from this article', onSelect: () => setFollowing(true) },
    { id: 'related', label: 'Show related in the Feed', onSelect: () => navigate({ name: 'feed', params: { related_item: String(detail.id) } }) },
  ]

  return (
    <>
      <div className="r-readerbar__actions">
        <VoteButtons itemId={detail.id} vote={state.vote} always tipBelow />
        <Separator />
        <SaveButton id={detail.id} base={detail.state} size="md" tooltipSide="bottom" />
        {filingOn && <FileButton itemId={detail.id} filing={detail.filing} filed={detail.filed} />}
        {!assist.open.reader && (
          <>
            <Separator />
            <IconButton label="Ask the assistant about this story" icon={<IconAsk size={18} />} onClick={() => setAssistOpen('reader', true)} tooltipSide="bottom" />
          </>
        )}
        {(original || hasOtherSources) && <Separator />}
        {original && <IconButton label="Open the original page" icon={<IconOpenOriginal size={18} />} onClick={() => openExternal(original)} tooltipSide="bottom" />}
        {original && <CopyLinkButton url={original} />}
        {hasOtherSources && <OtherSources detail={detail} />}
        <Separator />
        {isPaper && (
          <Button variant="quiet" size="sm" onClick={onTogglePdf} aria-pressed={showPdf}>
            {showPdf ? 'Text' : 'PDF'}
          </Button>
        )}
        <span className="r-readerbar__width">
          <WidthButtons />
        </span>
        <Separator />
        <Menu label="More actions" items={moreItems} trigger={<IconButton label="More" icon={<IconMore size={18} />} tooltipSide="bottom" />} />
      </div>
      <FollowDialog key={detail.id} open={following} source={{ kind: 'item', id: detail.id }} onClose={() => setFollowing(false)} />
    </>
  )
}

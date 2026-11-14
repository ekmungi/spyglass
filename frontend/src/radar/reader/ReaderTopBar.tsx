// ReaderTopBar: Back, publication and date, reading time, then the few actions a reader needs:
// Open original, Save, File in vault (queue), Follow, the assistant, and a More menu for the rest.
import { useState } from 'react'
import type { ItemDetail } from '../api/types'
import { TEXT_WIDTH } from '../appearance/catalog'
import { FileButton } from '../filing/FileButton'
import { FollowDialog } from '../follow/FollowDialog'
import { setAssistOpen, useAssistState } from '../assistant/assistStore'
import { openClaudeDialog } from '../claude/claudeStore'
import { SaveButton } from '../components/SaveButton'
import { useAppearance } from '../hooks/useAppearance'
import { formatDate, sentByYou } from '../lib/format'
import { readingLabel } from './readingLabel'
import { openExternal, safeHttpUrl } from '../lib/safeUrl'
import { goBack, navigate } from '../router'
import { useFilingConfigured } from '../state/filingConfigured'
import { setVote, useItemState } from '../state/itemState'
import { Button, IconAsk, IconBack, IconButton, IconExpand, IconFollow, IconMore, IconOpenOriginal, Menu, toast, type MenuItem } from '../ui'

export interface ReaderTopBarProps {
  detail: ItemDetail
  showPdf: boolean
  onTogglePdf: () => void
}

/** "Publication · 12 Nov 2026 · 6 min read" (or "Sent by you …" for captured items). */
function readerMeta(detail: ItemDetail): string {
  return [
    detail.reader?.site || detail.origin,
    formatDate(detail.published_at),
    readingLabel(detail.reader),
    detail.state.from_user ? sentByYou(detail.state.captured_via) : null,
  ]
    .filter(Boolean)
    .join(' · ')
}

/** The sticky bar at the top of the reader. */
export function ReaderTopBar({ detail, showPdf, onTogglePdf }: ReaderTopBarProps) {
  const state = useItemState(detail.id, detail.state)
  const assist = useAssistState()
  // The File in vault control exists only where the reader has set filing up.
  const filingOn = useFilingConfigured()
  const { appearance, stepWidth } = useAppearance()
  const [following, setFollowing] = useState(false)
  const isPaper = detail.reader?.kind === 'paper' && detail.reader.status === 'ok'

  // Only a plain web address is ever opened or copied as "the original".
  const original = safeHttpUrl(detail.url)
  const moreItems: MenuItem[] = [
    { id: 'more', label: 'More like this', checked: state.vote === 'more', onSelect: () => void setVote(detail.id, detail.state, 'more') },
    { id: 'less', label: 'Less like this', checked: state.vote === 'less', onSelect: () => void setVote(detail.id, detail.state, 'less') },
    {
      id: 'narrower',
      label: 'Narrower text',
      disabled: appearance.textWidth <= TEXT_WIDTH.min,
      onSelect: () => stepWidth(-TEXT_WIDTH.quickStep),
    },
    {
      id: 'wider',
      label: 'Wider text',
      disabled: appearance.textWidth >= TEXT_WIDTH.max,
      onSelect: () => stepWidth(TEXT_WIDTH.quickStep),
    },
    ...(original
      ? [
          {
            id: 'copy',
            label: 'Copy link to original',
            onSelect: () =>
              navigator.clipboard?.writeText(original).then(
                () => toast('Link copied'),
                () => toast('Could not copy the link.', { tone: 'error' }),
              ),
          },
        ]
      : []),
    {
      id: 'related',
      label: 'Show related in the Feed',
      onSelect: () => navigate({ name: 'feed', params: { related_item: String(detail.id) } }),
    },
    {
      id: 'claude',
      label: 'Open in Claude Code…',
      onSelect: () => openClaudeDialog({ itemId: detail.id }),
    },
  ]

  const sourceItems: MenuItem[] = [
    { id: `self-${detail.id}`, label: detail.origin, checked: true, onSelect: () => undefined },
    ...detail.story_sources
      .filter((source) => source.item_id !== detail.id)
      .map((source) => ({ id: String(source.item_id), label: source.name, onSelect: () => navigate({ name: 'item', id: source.item_id }, { replace: true }) })),
  ]

  return (
    <div className="r-readerbar">
      <div className="r-readerbar__left">
        <IconButton label="Back" icon={<IconBack size={18} />} onClick={() => goBack()} tooltipSide="bottom" />
        <p className="r-readerbar__meta">{readerMeta(detail)}</p>
      </div>
      <div className="r-readerbar__actions">
        {sourceItems.length > 1 && (
          <Menu
            label="Other sources for this story"
            items={sourceItems}
            trigger={
              <Button variant="quiet" size="sm">
                {sourceItems.length} sources <IconExpand size={14} />
              </Button>
            }
          />
        )}
        {isPaper && (
          <Button variant="quiet" size="sm" onClick={onTogglePdf} aria-pressed={showPdf}>
            {showPdf ? 'Text' : 'PDF'}
          </Button>
        )}
        {original && (
          <Button variant="quiet" size="sm" icon={<IconOpenOriginal size={14} />} onClick={() => openExternal(original)}>
            Open original
          </Button>
        )}
        {filingOn && <FileButton itemId={detail.id} filing={detail.filing} filed={detail.filed} />}
        <SaveButton id={detail.id} base={detail.state} size="md" tooltipSide="bottom" />
        <Button variant="quiet" size="sm" icon={<IconFollow size={14} />} onClick={() => setFollowing(true)} title="Follow topics from this article">
          Follow
        </Button>
        {!assist.open.reader && (
          <IconButton label="Ask the assistant" icon={<IconAsk size={18} />} onClick={() => setAssistOpen('reader', true)} tooltipSide="bottom" />
        )}
        <Menu label="More actions" items={moreItems} trigger={<IconButton label="More" icon={<IconMore size={18} />} tooltipSide="bottom" />} />
      </div>
      <FollowDialog key={detail.id} open={following} source={{ kind: 'item', id: detail.id }} onClose={() => setFollowing(false)} />
    </div>
  )
}

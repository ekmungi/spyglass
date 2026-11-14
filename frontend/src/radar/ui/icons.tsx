// Icons by meaning: <IconSaveForLater size={16} />. Each is a lucide glyph from iconGlyphs.ts drawn with
// the shared stroke, a size from the scale, currentColor, and hidden from screen readers unless
// it is given a label (an icon inside a labelled button needs none).
import type { LucideIcon, LucideProps } from 'lucide-react'
import { ICON_GLYPHS, ICON_STROKE, type IconSize } from './iconGlyphs'

export interface IconProps extends Omit<LucideProps, 'size' | 'strokeWidth' | 'absoluteStrokeWidth' | 'ref' | 'color'> {
  size?: IconSize
  /** Only for an icon that stands alone and carries meaning; it then becomes role="img". */
  label?: string
}

/** Draw `glyph` with the shared stroke and size scale; decorative (aria-hidden) unless labelled. */
export function Icon({ glyph: Glyph, size = 16, label, className, ...rest }: IconProps & { glyph: LucideIcon }) {
  const a11y = label ? { role: 'img', 'aria-label': label } : { 'aria-hidden': true as const }
  return (
    <Glyph
      size={size}
      strokeWidth={ICON_STROKE}
      focusable="false"
      className={['r-icon', className ?? ''].filter(Boolean).join(' ')}
      {...a11y}
      {...rest}
    />
  )
}

/* One component per meaning (arrow components, so Fast Refresh keeps working). */
export const IconToday = (props: IconProps) => <Icon glyph={ICON_GLYPHS.today} {...props} />
export const IconFeed = (props: IconProps) => <Icon glyph={ICON_GLYPHS.feed} {...props} />
export const IconWatch = (props: IconProps) => <Icon glyph={ICON_GLYPHS.watch} {...props} />
export const IconPapers = (props: IconProps) => <Icon glyph={ICON_GLYPHS.papers} {...props} />
export const IconSources = (props: IconProps) => <Icon glyph={ICON_GLYPHS.sources} {...props} />
export const IconProfile = (props: IconProps) => <Icon glyph={ICON_GLYPHS.profile} {...props} />
export const IconSettings = (props: IconProps) => <Icon glyph={ICON_GLYPHS.settings} {...props} />
export const IconThemeLight = (props: IconProps) => <Icon glyph={ICON_GLYPHS.themeLight} {...props} />
export const IconThemeDark = (props: IconProps) => <Icon glyph={ICON_GLYPHS.themeDark} {...props} />
export const IconAsk = (props: IconProps) => <Icon glyph={ICON_GLYPHS.ask} {...props} />
export const IconSaveForLater = (props: IconProps) => <Icon glyph={ICON_GLYPHS.saveForLater} {...props} />
export const IconSaved = (props: IconProps) => <Icon glyph={ICON_GLYPHS.saved} {...props} />
export const IconFileInVault = (props: IconProps) => <Icon glyph={ICON_GLYPHS.fileInVault} {...props} />
export const IconQueued = (props: IconProps) => <Icon glyph={ICON_GLYPHS.queued} {...props} />
export const IconPreparing = (props: IconProps) => <Icon glyph={ICON_GLYPHS.preparing} {...props} />
export const IconFiled =(props: IconProps) => <Icon glyph={ICON_GLYPHS.filed} {...props} />
export const IconFollow = (props: IconProps) => <Icon glyph={ICON_GLYPHS.follow} {...props} />
export const IconOpenOriginal = (props: IconProps) => <Icon glyph={ICON_GLYPHS.openOriginal} {...props} />
export const IconExternal = (props: IconProps) => <Icon glyph={ICON_GLYPHS.external} {...props} />
export const IconMore = (props: IconProps) => <Icon glyph={ICON_GLYPHS.more} {...props} />
export const IconClose = (props: IconProps) => <Icon glyph={ICON_GLYPHS.close} {...props} />
export const IconClosePanel = (props: IconProps) => <Icon glyph={ICON_GLYPHS.closePanel} {...props} />
export const IconBack = (props: IconProps) => <Icon glyph={ICON_GLYPHS.back} {...props} />
export const IconExpand = (props: IconProps) => <Icon glyph={ICON_GLYPHS.expand} {...props} />
export const IconSelected = (props: IconProps) => <Icon glyph={ICON_GLYPHS.selected} {...props} />
export const IconSearch = (props: IconProps) => <Icon glyph={ICON_GLYPHS.search} {...props} />
export const IconFilter = (props: IconProps) => <Icon glyph={ICON_GLYPHS.filter} {...props} />
export const IconHelp = (props: IconProps) => <Icon glyph={ICON_GLYPHS.help} {...props} />
export const IconAdd =(props: IconProps) => <Icon glyph={ICON_GLYPHS.add} {...props} />
export const IconSend = (props: IconProps) => <Icon glyph={ICON_GLYPHS.send} {...props} />
export const IconStop = (props: IconProps) => <Icon glyph={ICON_GLYPHS.stop} {...props} />
export const IconCopy = (props: IconProps) => <Icon glyph={ICON_GLYPHS.copy} {...props} />
export const IconPause = (props: IconProps) => <Icon glyph={ICON_GLYPHS.pause} {...props} />
export const IconResume = (props: IconProps) => <Icon glyph={ICON_GLYPHS.resume} {...props} />
export const IconRemove = (props: IconProps) => <Icon glyph={ICON_GLYPHS.remove} {...props} />
export const IconUndo = (props: IconProps) => <Icon glyph={ICON_GLYPHS.undo} {...props} />
export const IconRetry = (props: IconProps) => <Icon glyph={ICON_GLYPHS.retry} {...props} />
export const IconPaper = (props: IconProps) => <Icon glyph={ICON_GLYPHS.paper} {...props} />
export const IconVideo = (props: IconProps) => <Icon glyph={ICON_GLYPHS.video} {...props} />
export const IconCode = (props: IconProps) => <Icon glyph={ICON_GLYPHS.code} {...props} />
export const IconRegulator = (props: IconProps) => <Icon glyph={ICON_GLYPHS.regulator} {...props} />
export const IconFromYou = (props: IconProps) => <Icon glyph={ICON_GLYPHS.fromYou} {...props} />
export const IconWarning = (props: IconProps) => <Icon glyph={ICON_GLYPHS.warning} {...props} />
export const IconPartial = (props: IconProps) => <Icon glyph={ICON_GLYPHS.partial} {...props} />

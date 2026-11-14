// The icon vocabulary: one lucide glyph per meaning in Spyglass. Pages never import lucide-react
// directly; they use the Icon* components in icons.tsx, which are built from this table. Two
// meanings never share a glyph (a test checks it), so an icon always says one thing.
import {
  ArrowLeft,
  ArrowUp,
  ArrowUpRight,
  Binoculars,
  Bookmark,
  BookmarkCheck,
  Check,
  ChevronDown,
  CircleDashed,
  CircleHelp,
  CodeXml,
  Copy,
  Ellipsis,
  ExternalLink,
  FileClock,
  FileSearch,
  FileText,
  FolderCheck,
  FolderInput,
  Hourglass,
  Inbox,
  Landmark,
  ListFilter,
  MessageSquare,
  Minus,
  Moon,
  Newspaper,
  PanelRightClose,
  Pause,
  Play,
  Plus,
  Radar,
  RotateCw,
  Rows3,
  Rss,
  Search,
  Settings,
  Square,
  SquarePlay,
  Sun,
  TriangleAlert,
  Undo2,
  UserRound,
  X,
  type LucideIcon,
} from 'lucide-react'

export const ICON_GLYPHS = {
  // Navigation targets in the rail.
  today: Newspaper, // the morning brief
  feed: Rows3, // every collected item, one row each
  watch: Binoculars, // companies and topics kept in view
  papers: FileSearch, // find papers
  sources: Rss, // the feeds Spyglass reads
  profile: UserRound, // your interest profile
  settings: Settings,
  help: CircleHelp, // the How to page: step-by-step help for each task
  themeLight: Sun,
  themeDark: Moon,
  // Actions on an item.
  ask: MessageSquare, // ask the assistant
  saveForLater: Bookmark, // a bookmark means save for later, nothing else
  saved: BookmarkCheck, // the saved state of the same control
  fileInVault: FolderInput, // file a note into the vault: into a folder, unlike the bookmark
  queued: Hourglass, // waiting in the filing queue: not filed yet
  preparing: FileClock, // the reader's clean copy is being made: a page with a clock
  filed: FolderCheck, // the quiet confirmed state after filing
  follow: Radar, // keep scanning for more like this
  openOriginal: ExternalLink, // open the original page in the browser
  external: ArrowUpRight, // a plain link that leaves Spyglass
  // Controls.
  more: Ellipsis,
  close: X, // close a dialog, dismiss a chip
  closePanel: PanelRightClose, // fold the assistant panel away
  back: ArrowLeft,
  expand: ChevronDown, // disclosure: open a menu or a collapsed row
  selected: Check, // the chosen entry in a menu
  search: Search,
  filter: ListFilter,
  add: Plus,
  send: ArrowUp,
  stop: Square, // stop a streaming answer
  copy: Copy,
  pause: Pause,
  resume: Play,
  remove: Minus, // take an entry out of a list (not a deletion)
  undo: Undo2,
  retry: RotateCw,
  // Kinds and states; always shown beside their text label, never alone.
  paper: FileText,
  video: SquarePlay,
  code: CodeXml,
  regulator: Landmark,
  fromYou: Inbox, // something you sent in yourself
  warning: TriangleAlert,
  partial: CircleDashed, // only part of the text could be read
} as const satisfies Record<string, LucideIcon>

export type IconMeaning = keyof typeof ICON_GLYPHS

/** The stroke width every icon uses: a fine line that sits with 500-weight interface text. */
export const ICON_STROKE = 1.5

/** The size steps, in px. 14 inside small buttons and chips, 16 by default, 18 in bars, 20 for emphasis. */
export const ICON_SIZES = [14, 16, 18, 20] as const
export type IconSize = (typeof ICON_SIZES)[number]

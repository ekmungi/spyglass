# Radar UI kit

The building blocks of the redesigned Spyglass interface. Every page under
`frontend/src/radar/pages/` is built from these tokens and primitives, so a new page looks like
it belongs without new CSS. Import primitives from `../ui` (the folder's `index.ts`).

## Direction in one paragraph

A calm, editorial morning paper for one reader. Typography does the work: Newsreader (a variable
serif with optical sizes) for headlines and reading, Inter for interface text. Generous
whitespace, one ink-blue accent, hairline rules instead of boxes, no gradients, no drop shadows,
no emoji, no decorative icons (icons appear only where they label an action or a navigation
target). Fewer visible controls: anything not needed for reading, opening, asking, saving or
sending a link goes into a `Menu`.

## Tokens (`tokens.css`)

All values are CSS variables on `:root`; dark mode swaps the colour roles only.

| Group | Variables | Use |
|---|---|---|
| Colour | `--paper`, `--paper-raised`, `--surface` | page, menus/dialogs, hover wash and user bubbles |
| | `--ink`, `--ink-2`, `--muted`, `--faint` | headlines, reading text, meta lines, placeholders |
| | `--rule`, `--rule-strong` | hairlines, control outlines |
| | `--accent`, `--accent-soft`, `--accent-ink` | links and active state; selection wash; text on filled accent |
| | `--danger`, `--ok` | inline error and confirmation text only |
| Type | `--font-serif`, `--font-sans`, `--font-mono` | families |
| | `--text-2xs` … `--text-display` | scale: 11.5, 12.5, 13.5, 15 (UI), 18.5 (reading), 21 (lede), 18/23/34 (headlines), clamp(40–58) (date) |
| | `--leading-tight/snug/ui/read` | 1.18 / 1.35 / 1.45 / 1.62 |
| Space | `--space-1` … `--space-16` | 4px grid (4, 8, 12, 16, 20, 24, 32, 40, 48, 64) |
| Radius | `--radius-sm/md/lg/pill` | 4 / 6 / 10 / 999; content never sits in a box |
| Layout | `--measure`, `--measure-read`, `--rail-width`, `--assist-width` | 680px column, 700px reader column, 212px rail, 380px assistant |
| Motion | `--dur-fast`, `--dur`, `--dur-slow` | 120 / 200 / 280ms: state changes / small overlays / large surfaces; all 0 under reduced motion |
| | `--ease-enter`, `--ease-exit` (`--ease` = enter) | decelerating for arriving, accelerating for leaving |
| | `--shift` | 6px, the one small translation (0 under reduced motion) |
| Focus | `--focus-ring` | apply with `box-shadow: var(--focus-ring)` on `:focus-visible`; it fades in over `--dur-fast` |

Theme: `<html data-theme="light|dark">` forces a theme; no attribute follows the system. Use
`useTheme()` from `../hooks/useTheme` to read or toggle it.

## Primitives (`index.ts`)

| Primitive | Usage |
|---|---|
| `Button` | `<Button variant="primary" onClick={save}>Save</Button>`; variants `primary` (filled accent, one per view), `secondary` (hairline outline), `quiet` (text only); `size="sm"`; optional `icon`. |
| `IconButton` | `<IconButton label="Close" icon={<IconClose size={16} />} onClick={close} />`; `label` is the accessible name and the tooltip; `pressed` for toggles. |
| `Icon*` | `<IconSaveForLater size={16} />`; one component per meaning (table below); hidden from screen readers unless given `label`. `<Icon glyph={…} />` draws any lucide glyph the same way. |
| `usePresence` | `const p = usePresence(open, '--dur')`; render while `p.mounted`, put `data-state={p.state}` on the element, style `[data-state="closed"]` as the exit. |
| `Chip` | `<Chip selected={on} onClick={toggle}>Health</Chip>`; a toggle filter chip (`aria-pressed`); optional `count`. |
| `Pill` | `<Pill tone="accent">Top</Pill>`; a small static label; tones `neutral`, `accent`, `muted`. |
| `Rule` | `<Rule spacing="lg" />`; a hairline `<hr>`; `strong` for a darker line. |
| `Skeleton` | `<Skeleton lines={3} />` or `<Skeleton width="40%" height={28} />`; loading placeholder. |
| `Tooltip` | `<Tooltip label="Save for later"><button>…</button></Tooltip>`; shows on hover and focus. |
| `Menu` | `<Menu label="More actions" trigger={<IconButton … />} items={[{ id: 'less', label: 'Less like this', onSelect }]} />`; keyboard navigable; items may be `disabled`, `checked`, or carry a `hint`. |
| `Select` | `<Select label="Kind" value={v} onChange={setV} options={[{ value: '', label: 'All kinds' }]} />`; styled native select; supports `groups`; `hideLabel` keeps the label for screen readers only. |
| `Dialog` | `<Dialog open={open} onClose={close} title="Add a link" footer={<Button …/>}>…</Dialog>`; modal, Esc closes, focus returns to the opener. |
| `Toast` | `toast('Saved for later')` or `toast('Could not save', { tone: 'error', action: { label: 'Retry', onClick } })`; `<ToastViewport />` is mounted once by the app shell. |
| `EmptyState` | `<EmptyState title="No sources yet" body="…" action={<Button …/>} />`; every empty screen gets one, and it says what to do next. |
| `SectionHeading` | `<SectionHeading note="3 picked from 96">Top stories</SectionHeading>`; small-caps heading over a hairline; `as="h3"` for nested. |

## Motion

Motion answers an action and shows what changed; nothing moves on its own except a loading
shimmer. Only `opacity`, the transform family (`transform`, `scale`, `translate`) and colours
animate, never size or position, and nothing bounces or takes longer than 320ms.

- **State** (hover, press, focus ring, selected chip): colour over `--dur-fast`. A press nudges a
  control down 1px with `translate`.
- **Small overlays**: a `Menu` opens out of its trigger's corner (scale 0.97 to 1 with a fade),
  a `Tooltip` fades in after 300ms and out at once, a toast rises `--shift` from the bottom edge.
  Entrances take `--dur`, exits `--dur-fast`.
- **Large surfaces**: a `Dialog` fades its backdrop and lifts its panel `--shift` over
  `--dur-slow`, and leaves over `--dur`. A dialog that replaces another keeps the page dimmed.
- **Page changes**: a View Transition cross-fades the main column (the old page leaves over
  `--dur-fast`, the new one rises `--shift` over `--dur-slow`); the rail stays still and only its
  marker glides. Filter changes on the same page do not animate.
- **Lists**: rows mount without animation (the Feed is virtualised); only hover and selection
  colours transition.
- **Entering** uses `@starting-style` and a `transition`, so an interrupted entrance reverses
  smoothly. **Exiting** needs the element to stay mounted: use `usePresence`, which reads the exit
  duration from the tokens and is 0 under reduced motion.

## Icons (`icons.tsx`)

One family (lucide), one stroke (1.5), four sizes: 14 inside small buttons and chips, 16 by
default, 18 in bars and the rail, 20 for emphasis. Icons take `currentColor`. Never import
`lucide-react` in a page; add a meaning to `iconGlyphs.ts` instead, so no two meanings share a glyph.

| Meaning | Component | lucide glyph |
|---|---|---|
| Today | `IconToday` | `Newspaper` |
| Feed | `IconFeed` | `Rows3` |
| Watch | `IconWatch` | `Binoculars` |
| Find papers | `IconPapers` | `FileSearch` |
| Sources | `IconSources` | `Rss` |
| Profile | `IconProfile` | `UserRound` |
| Settings | `IconSettings` | `Settings` |
| Light / dark theme | `IconThemeLight` / `IconThemeDark` | `Sun` / `Moon` |
| Ask the assistant | `IconAsk` | `MessageSquare` |
| Save for later / saved | `IconSaveForLater` / `IconSaved` | `Bookmark` / `BookmarkCheck` |
| File in the vault / waiting to be filed / filed | `IconFileInVault` / `IconQueued` / `IconFiled` | `FolderInput` / `Hourglass` / `FolderCheck` |
| Follow more like this | `IconFollow` | `Radar` |
| Open the original | `IconOpenOriginal` | `ExternalLink` |
| A link that leaves Spyglass | `IconExternal` | `ArrowUpRight` |
| More actions | `IconMore` | `Ellipsis` |
| Close, dismiss | `IconClose` | `X` |
| Fold the assistant away | `IconClosePanel` | `PanelRightClose` |
| Back | `IconBack` | `ArrowLeft` |
| Open a menu or row | `IconExpand` | `ChevronDown` |
| Chosen menu entry | `IconSelected` | `Check` |
| Search / filter | `IconSearch` / `IconFilter` | `Search` / `ListFilter` |
| Add | `IconAdd` | `Plus` |
| Send / stop an answer | `IconSend` / `IconStop` | `ArrowUp` / `Square` |
| Copy | `IconCopy` | `Copy` |
| Pause / resume | `IconPause` / `IconResume` | `Pause` / `Play` |
| Remove from a list | `IconRemove` | `Minus` |
| Undo / retry | `IconUndo` / `IconRetry` | `Undo2` / `RotateCw` |
| Paper, video, code, regulator | `IconPaper`, `IconVideo`, `IconCode`, `IconRegulator` | `FileText`, `SquarePlay`, `CodeXml`, `Landmark` |
| From you | `IconFromYou` | `Inbox` |
| Warning / partial text | `IconWarning` / `IconPartial` | `TriangleAlert` / `CircleDashed` |

Rules:

- An icon labels an action or a destination; it is never decoration. Kind and state icons
  (paper, video, from you, partial) appear only beside their text label.
- An icon-only control is an `IconButton`: its `label` is the accessible name and the tooltip.
  Keep the tooltip on; it hides itself while the button's menu is open.
- An icon next to text is hidden from screen readers (the default). Give `label` only to an icon
  that stands alone and carries meaning that no text nearby says.

## Layout conventions

- The shell (`../shell/`) owns the left rail, the main scroll container and the assistant panel.
  A page renders only its own content; it does not set its own background or scroll container.
- Wrap page content in `<div className="r-page">` for the standard column (centered, `--measure`
  wide, top padding). Use `r-page r-page--wide` for tables or registers that need more width.
- A page title is `<h1 className="r-page-title">`, optionally followed by
  `<p className="r-page-meta">` for one quiet line of meta.
- Group content with `SectionHeading` and hairline `Rule`s, not cards or boxes. Lists are rows
  separated by hairlines (`<ul className="r-rows">` gives each `li` a bottom rule).
- Text classes: `r-serif` (reading serif), `r-meta` (12.5px muted Inter), `r-headline`
  (serif row headline), `r-sr-only` (visually hidden).
- Data comes from `../api/client` (typed, one function per endpoint; failures throw an
  `ApiError` whose `message` is fit to show) and `../hooks/useResource`
  (`const { data, error, loading, reload } = useResource('watch', getWatch)`). Show `Skeleton`
  while loading, `errorMessage(error)` (from `../api/errors`) with a Retry `Button` on error,
  and `EmptyState` when empty. Import every shape from `../api/types`.
- Open an item with `<ItemLink id={item.id}>` (`../components/ItemLink`): a real link whose click
  goes through the router, so Back returns to the same scroll position. In code, `openItem(id)`
  or `navigate({ name: 'item', id })` from `../router`.
- Saving goes through `<SaveButton id={item.id} base={item.state} />` (`../components/SaveButton`)
  or `toggleSave(id, state)` / `setVote(id, state, 'more')` from `../state/itemState`, which update
  every visible copy of the item at once and roll back with an error toast on failure.
- Overlay and form styles (`r-field`, `r-input`, `r-textarea`, dialog, toast) live in
  `overlays.css`; all CSS files here are loaded once by `../styles.css`.
- Tailwind utilities are available and mapped to the tokens (`text-muted`, `bg-surface`,
  `border-rule`, `font-serif` …); prefer the classes above for anything the README names.
- Sample mode: append `?mock=1` to the URL (or set `VITE_RADAR_MOCK=1`) to click through the
  whole interface with fixtures from `../mock/` and no backend. `?mock=1&brief=none` starts
  without a brief, to show Compose now.

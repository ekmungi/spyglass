# Changelog

All notable changes to the Spyglass plugin are recorded here. Versions match the root
`manifest.json` / `versions.json` and the matching GitHub release tag (no `v` prefix).
Format loosely follows [Keep a Changelog](https://keepachangelog.com/); this project uses
0.x minor bumps per notable release.

## [0.32.2] - 2026-11-10

First public release: AGPL-3.0 licence, example settings and documentation for new users, and
one fix to card labels.

### Added
- **Licence.** `LICENSE` holds the GNU Affero General Public License 3.0, and `pyproject.toml` and
  both `package.json` files declare `AGPL-3.0-or-later`. The reason is PyMuPDF, the PDF text
  extractor, which is licensed AGPL-3.0 or commercially (see the README's Licence section).
- **A README for new users:** requirements, install steps, an "Optional Claude skills" section that
  says what each optional skill or tool must do and what happens without it, and what leaves your
  machine.
- `scripts/pre_push_guard.py`, an optional git pre-push hook that refuses a push when a commit the
  remote lacks carries a private tracker's record number, a personal home-folder path, a personal
  email address or a term you list locally.

### Changed
- The plugin's *Service repository path* setting now starts empty, and the plugin shows a notice
  until it is set (unless *Connect only* is on). A path you already saved is kept.
- `.env.example` holds placeholder paths instead of real ones.
- Comments, docstrings and test names no longer cite private planning notes, and the bundled skills
  and the prompts Spyglass sends to Claude describe the optional skills they can use instead of
  naming them. The example inbox channel is now `paper-inbox`. Apart from the fix below, nothing
  else in how Spyglass behaves has changed.

### Fixed
- **Cards show the feed name you chose.** A card's source label was always the feed's own title,
  which for some feeds is raw text: an arXiv search feed showed its whole search query. When you
  have named a feed in the Feeds tab, its cards now show that name in the list, the reader, search,
  similar articles and new Daily Briefs. Renaming a feed relabels its existing cards. Feeds you
  have not named keep their own title.

## [0.32.1] - 2026-11-10

Security fixes: a web page you visit, or the text of a saved article, can no longer make Spyglass
act.

### Fixed
- **Requests from other sites are refused.** A web page could send Spyglass a request that stopped
  it or started an action, because a browser sends such a request even when the page cannot read
  the reply. Spyglass now refuses any request that changes something when the browser says it
  comes from another site. The Obsidian plugin, the dashboard, Claude and scripts are unaffected.
  The endpoints that open a Claude session with text in it also require a JSON body.
- **Requests addressed to another name are refused.** A web page could point its own domain at
  your computer (DNS rebinding) and then read your cards. The service now answers only requests
  addressed to `127.0.0.1` or `localhost`, on any port.
- **File it can move only its own note.** The filing run used to hold your Obsidian server's
  `vault_move`, so text in an article could have steered it into moving other notes. The run now
  only names a folder. Spyglass checks the folder, moves the job's note itself through your
  Obsidian server without overwriting anything, and checks that it arrived. Your Obsidian
  server's key is no longer written to a file for the run, and an error never shows it.
- **Background runs get only the tools they need.** Besides Spyglass's own tools, a run now has
  only Read, Glob and Grep. Before, it could also reach tools that schedule tasks, start remote
  routines or message your other Claude sessions.
- A move that Obsidian finished just before an error is now recorded, so the item no longer
  points at a missing file. A "filed" report counts only when Spyglass made the move, and a run
  can no longer act after it has reported.

## [0.32.0] - 2026-10-16

Claude prepares and files detailed notes in the background, without opening a window.

### Added
- **Prepare detail.** One click in the reader: a hidden Claude run reads the item, your
  interests and your vault's projects and areas, and writes a detailed note with links to related
  notes. Spyglass saves it in `03 RESOURCES/Spyglass/Brief notes/<date>/`.
- **File it.** A hidden Claude run picks the folder from your vault map and moves the note through
  your Obsidian MCP server, so links and comments attached to the note follow; it says where and why, and
  Spyglass checks the note is there. Spyglass opens Obsidian first when it is closed.
- **Delete note** moves an unfiled detailed note to the vault's trash (a thumbs down).
- The reader shows each job's progress, can cancel it, and shows the reason when it fails, with
  Try again. Jobs appear in the Activity tab. New settings: Claude command, job time limit, detail
  notes folder, Obsidian MCP server, Obsidian address.
- Background runs are locked down: they ignore your Claude settings files, load only Spyglass's
  and the Obsidian server, may read only inside the vault, and are denied shell, writes, web and
  the Obsidian write tools. Dataview JS in a note Claude writes is kept as plain code.
- A note moved without Spyglass knowing is found again by its `spyglass_item` property; new MCP
  tool `set_item_note` for the linked session.

- **A model per job, and your Claude limits in view.** Prepare detail runs on Sonnet
  and File it on Haiku instead of Claude Code's default (Opus on a Max plan); both are settings.
  Each job records its model and the share of your 5-hour and weekly limits Claude reports, shown
  in the reader. When a limit is reached, the queue waits for the reset instead of failing.
- **End the link.** The header gains an unlink button, and the link to the Claude session ends
  about a minute and a half after the last Spyglass window closes. The session is told why.

### Fixed
- **Stopping the service.** `POST /api/shutdown` answered "stopping" but stopped nothing; it now
  stops the service, within 5 seconds even while Claude sessions keep their connection open.
- **File it chose Spyglass's own folder.** On the first real test both notes were "filed" into
  `03 RESOURCES/Spyglass`. Filing now never uses Spyglass's own folders, Spyglass refuses a
  filing that lands in one, and a note there counts as not filed yet.
- **New Claude sessions starting outside the vault.** A Claude desktop bug starts a link's session
  in an empty scratch folder when the folder is already selected, while the chip shows the vault.
  Spyglass now spells the folder differently on each link to avoid it; a session that still opens
  outside the vault says so, and the header says when a new session has not linked.

### Changed
- **Read detail** replaces the toolbar's Read briefing button and shows the note without its
  properties block.

## [0.31.0] - 2026-10-15

Claude now opens in the Claude desktop app instead of a terminal, one Claude session at a time is
linked to Spyglass, and papers you share in Slack are filed in your vault with a debrief.

### Changed
- **Every Claude button opens the Claude desktop app.** The top-bar Claude button, the selection
  bar, Send to Claude, Research on the web and the brief's Open in Claude now
  open a session in the desktop app's Code tab, in your vault, with the request already typed
  in and the selected cards named. You press Enter. No PowerShell window opens any more.
- **The brief's Open in Claude opens one session** for the bullets you picked. The "One per
  bullet" option is gone: each desktop session asks to confirm its folder, so it would have meant
  one dialog per bullet.

### Added
- **One linked Claude session.** The header shows whether a Claude session is linked and
  when it last called Spyglass; its button opens a new session that links itself with a one-time
  code. Opening another moves the link, and the earlier session is refused with a clear message.
  The dashboard's Claude buttons talk to the linked session: with one linked they select the
  items and copy the request to paste there, otherwise they open a new linked session. Process
  inbox still runs in its own session.
- **Item codes.** Every item shows its code (`#1042`), copied with one click. In Claude,
  `get_item` resolves a code, and "this one" and "these" mean the item open in the reader and the
  ticked items (`get_selection`). Spyglass also lists its likeliest items as MCP resources for
  Claude's @ list; the Claude desktop Code tab does not show them (its @ list is files and
  folders only), Claude in a terminal does. New MCP tools `link_session`, `get_item` and
  `get_instructions`.
- **The paper inbox.** Share papers in one Slack channel; **Process inbox** on the new
  Inbox tab opens a Claude desktop session that files each paper in your vault with a paper-filing
  skill, writes a debrief into its note and reports back. The tab lists the papers with your
  own words, a short summary, **Open the debrief** and **Discuss in Claude**, and shows how the
  last run went (or why it failed). A paper shared twice stays one card. Set the channel in
  Settings. New skill `spyglass-inbox`; new MCP tools `inbox_start`, `inbox_add_paper`,
  `inbox_file_paper`, `inbox_finish`.
- **A debrief for each inbox run.** After filing the papers, Claude writes one note on how
  they connect: which papers overlap, how they link to notes you already have, and ideas for your
  active projects. The Inbox tab lists the recent run debriefs; one click opens a debrief in
  Obsidian. New MCP tool `inbox_save_debrief`.
- **Spyglass registers itself with Claude.** At startup the service adds the `spyglass` MCP server
  to the vault's `.mcp.json`, keeping any other servers. No more copying the template by hand.
- **Long requests still arrive whole.** A request too long for a link is handed over through a
  new `get_handoff` tool.
- **If the desktop app cannot be opened**, the dashboard says so and offers to copy the request.

### Fixed
- **Feeds that block unknown programs can be added.** Adding and collecting feeds now sends the
  same browser-like identity as page fetching. When a feed still cannot be added, Spyglass says
  why: the site refused, the address could not be reached, or it is not a feed.
- **Claude no longer wipes an article's category** when it saves a summary without one. A
  category Claude gives joins your set, and a category you chose by hand is never replaced.
- The `spyglass` skill's review workflow matches what `get_review_queue` returns.
- **Claude connects to Spyglass at the exact address.** The vault's `.mcp.json` now points at
  `http://127.0.0.1:7777/mcp/`. The old `http://localhost:7777/mcp` answered with a redirect, and
  on Windows "localhost" can resolve to an address Spyglass does not listen on. Existing entries
  are corrected at startup.
- **Scrollbars no longer touch the content.** In every tab, including the Workspace card list
  and reader, the scrollbar sat flush against cards and buttons. It now sits clear of them with
  a gap, and every scrollbar uses the theme's colours.

### Removed
- **The chat inside the reader.** Conversations happen in the linked Claude session instead. Its
  OpenRouter client and `/api/chats` endpoints are gone; stored chats stay in the database for now.
- The terminal launcher (`launch.py`) and its `spawn_auto` setting.

## [0.30.0] - 2026-07-28

You can now ask questions about what you're reading without leaving the reader.

### Added
- **A chat box in the reader.** Ask something about the open article and the answer streams
  back, grounded in the text Spyglass has stored for it. It is for the questions that need no
  tools — "what's the actual claim here?", "does this contradict the other one?" — and it
  answers in about a second instead of opening a terminal.
- **Chat about several articles at once.** Select multiple cards and the conversation covers
  all of them; the answer says which article it is drawing on. A conversation belongs to that
  set of articles, so going back to the same selection returns to the same thread.
- **Conversations are kept.** They live in the database, not the page, so they survive opening
  another card, closing the reader, and reloading Spyglass entirely — and a reply that arrives
  while you are elsewhere is still waiting when you come back. Past chats also turn up in
  search, alongside the articles they were about.
- **"Continue in Claude."** When a question turns into real work, hand the whole conversation
  and its articles to a full Claude Code session without retyping anything. The chat box
  trades tools for speed; this is the door back to them.
- **"New thread"** starts a fresh conversation on the same articles — the cheapest way to keep
  a long-running chat fast.

### Notes
- Long conversations are handled by condensing the older turns once they pile up, while the
  **full transcript is always kept** — what gets shortened is only what is sent to the model.
- If an article has no stored full text, the chat says so and answers from the summary rather
  than pretending. Fetch the full text for a better answer.
- If you select more articles than fit in one request, Spyglass says which ones it had to
  shorten instead of quietly dropping them.
- The chat model is a setting (`chat_model`), currently defaulting to the same model the
  enrichment pipeline uses. A proper picker arrives with Settings → Models.

## [0.29.1] - 2026-07-28

A maintenance fix with no change to how Spyglass behaves — it repairs a flaw in how the
Daily Brief could be tested.

### Fixed
- **The brief composer no longer ignores the date it is told to work from.** It accepted an
  "as of this moment" argument and silently discarded it, deriving the day from the real
  clock instead. Nothing in the running app passes that argument, so briefs were never
  affected — but it meant five of the brief's own tests were quietly checking nothing, and
  they began failing on their own once the calendar moved far enough past the dates they
  seeded. The argument now does what every caller assumed; an explicitly supplied date still
  takes precedence.

### Notes
- No README change needed — no user-facing behaviour changed.
- Verified against a copy of the real database: the way the running service calls the
  composer resolves to exactly the same days before and after this change.

## [0.29.0] - 2026-07-28

Fetching an article's full text now keeps running in the background, and Spyglass keeps
showing you that it is — even after you move on to the next card.

### Changed
- **"Fetch full text" no longer loses track of itself.** Starting a fetch and then opening
  another card used to make the "fetching" message vanish, and coming back showed the empty
  "no content stored" state — as though the fetch had been thrown away. The fetch is now a
  queued background job whose progress is remembered by the service, so returning to the card
  still shows it working, and the text simply appears when it lands. Closing the reader or
  reloading the dashboard mid-fetch is equally safe.
  - *For the record: the work was never actually being lost.* Verified against a copy of the
    real database — a fetch interrupted by navigating away still ran to completion and stored
    its text. What was lost was only the ability to see it, which is what made it look broken.
- **Requesting a fetch is now instant.** The request returns as soon as the job is queued
  instead of holding the connection open for the whole retrieval, which since 0.28.0 could mean
  30–60 seconds on the slowest tier.

### Added
- **In-flight fetches are marked in the item list**, so a queued fetch is visible from anywhere
  in the app rather than only in the reader that started it.

### Fixed
- **Clicking "fetch full text" twice now fetches once.** A second click while one is already in
  flight joins the existing job instead of starting a duplicate retrieval.
- **A fetch cut short by a service restart is reported, not left hanging.** It comes back marked
  as interrupted, and can simply be requested again.
- One article failing to fetch can no longer stop the queue; the next one still runs.

## [0.28.0] - 2026-07-07

Spyglass now reads far more of the pages it used to give up on, and when a page genuinely
can't be read it tells you why instead of a silent "failed".

### Added
- **Resilient full-text fetching.** Pages that used to come back empty -- sites behind
  bot-protection or a "prove you're human" wall, pages that only render with JavaScript, and
  more PDF varieties -- are now read by trying progressively stronger methods in turn: a plain
  fetch, then one that mimics a real browser's network fingerprint, then a reader service that
  renders the page for us, then a real local headless browser as a last resort. Spyglass stops
  at the first method that works and remembers which one worked for each site, so the automatic
  pass doesn't keep paying for the slow paths.
- **A readable reason when a fetch fails.** Instead of a bare "could not be fetched", the reader
  now says what actually happened -- e.g. "blocked at the first tier (HTTP 403); the browser tier
  also failed" -- so a block is understandable and worth retrying, not a dead end.
- **Two new fetch settings** (both on by default): the reader-service tier and the local-browser
  tier can each be turned off if you prefer to keep every fetch fully on your machine. (The
  reader-service tier sends the failing page's URL to an external reader; the browser tier stays
  local.)

### Changed
- **PDF text extraction moved to PyMuPDF**, which reads more PDF layouts cleanly and lays the
  groundwork for future image / scanned-page support.

### Notes
- The local-browser fallback tier needs a one-time `patchright install chromium` (see the README).
  Without it, that single tier is skipped gracefully -- every other tier still works.
- Fetches are now capped at ~25 MB per download so a mislabeled giant file can't balloon memory.

## [0.27.0] - 2026-07-07

The Daily Brief now keeps a complete day-by-day history instead of folding older days into
one long "Earlier" digest, and it fills in a day that finished while you were away as soon as
you open Spyglass — no restart needed.

### Changed
- **One brief per day — the "Earlier" digest is gone.** Catching up after a gap used to
  collapse everything older than the four most recent days into a single, over-long "Earlier"
  roll-up that hid which days you'd actually seen. Now every un-briefed day within the two-week
  window gets its own brief, newest first, so the list reads as a clean per-day timeline. Days
  you've already been briefed on are never rebuilt, and any older "Earlier" digests you already
  have stay exactly as they were.

### Added
- **Briefs fill in when you open Spyglass, not only after a restart.** A day that closed while
  the app sat idle is now composed on your next open or refresh, so you no longer have to
  restart the service to see it. Composing does no work — and makes no network call — when
  nothing is due, and two overlapping refreshes can't compose the same day twice.

## [0.26.1] - 2026-07-06

Fixes the "Generate now" button and tidies selection after opening a Claude session.

### Fixed
- **"Generate now" now shows the brief it composes.** Since 0.26.0 the button always reported
  "Nothing new to brief," even right after composing one — the dashboard was still reading the old
  single-brief response while the service had switched to returning a *list* of briefs (one per
  publish-day). The freshly composed briefs are now prepended to the list and the newest opens
  automatically. (If you clicked Generate and saw no new brief, it was in fact composed — just never
  displayed; it shows up now.)
- **Honest feedback when a day is held back.** When a day is due but too heavy to summarize in one
  brief (its bucket pauses on the partition gate), the button now says "N day(s) held — too many
  items to compose right now; it retries automatically on the next refresh" instead of the
  misleading "Nothing new to brief."
- **Selection clears after opening a Claude session.** Selecting brief bullets (or list cards) and
  opening them in Claude Code now deselects them afterward, so the control reverts to its default
  and a stale selection can't be reused by accident. Backing out of the scope popover keeps your
  selection.

## [0.26.0] - 2026-07-06

Daily Brief now groups articles by the day they were **published**, not the day Spyglass collected them.

### Changed
- **Every brief is a publish-day.** A brief used to cover "everything collected since the last brief," so
  a single catch-up fetch could dump articles published across many days into one enormous brief (e.g. a
  158-item day). Now each article lands in the brief for the calendar day it was published (your local
  timezone), and each day gets its own brief. Resuming after Spyglass has been off automatically fills the
  missed days — capped at 5 briefs so a long gap doesn't bury you: the 4 most recent days each get their
  own brief, and everything older merges into one "Earlier" digest. Each day is composed once (a
  late-arriving article for a day that already has a brief is not folded back in). A one-time migration
  re-buckets your recent briefs into the new per-day shape on first launch.
- **New `brief_horizon_days` setting (default 14).** Bounds how far back briefs reach — only articles
  published within this window are eligible, so an older never-briefed backlog stays out of the catch-up.
  Tunable via the `SPYGLASS_BRIEF_HORIZON_DAYS` environment variable or the settings file.

## [0.25.5] - 2026-07-05

Daily Brief: one card, one bullet — no more padded, duplicate-linked briefs.

### Fixed
- **A thin day no longer gets padded into a fake multi-section brief.** When a day had only one relevant
  article, the brief could spin it into several bullets across invented sections (e.g. "economic doubts",
  "healthcare AI investment", "clinical LLMs") — all linking back to that single article, some of those
  angles reverse-engineered from your interests rather than the article itself. The compose now enforces
  one rule: each featured article is the main source of exactly one bullet. Genuinely-related articles
  group into a single bullet that cites all of them; unrelated ones get their own bullet; nothing is
  duplicated, dropped, or invented. A validation gate rejects and retries any draft that breaks this, so
  an over-split brief can't be saved. Verified live: the Jul-5 brief recomposed from 6 bullets to 1.
- **Clearer brief-list counts.** "1 article + 3 more" now reads "1 article, 3 also noticed" so the second
  number names the "Also noticed" tail instead of an opaque "+3 more".

## [0.25.4] - 2026-07-05

Daily Brief: related items you can actually see.

### Fixed
- **Per-bullet "Related" reading is back — inline and on demand.** Each brief bullet with related
  articles now shows a chevron on its right; clicking it expands a muted "Related: …" line of links at
  the bottom of that bullet (click again to collapse). This replaces a "+N" control that did nothing
  when clicked and shoved the bullet text sideways as it opened. Reader UI only.

## [0.25.3] - 2026-07-05

Layout and brief-reader polish.

### Fixed
- **The window no longer gets a stray scrollbar, and tabs stop looking "shrunk."** Every tab now fits the
  screen exactly and scrolls inside its own pane, instead of the whole window scrolling — most noticeable
  when zoomed in, where the Workspace could look squeezed into a corner with empty canvas below. Each tab's
  top bar (Workspace search/filters, the brief's Back/Recompose/Open-in-Claude row, the Feeds add bar) now
  stays put while only the content below it scrolls.
- **The Daily Brief's selection grip is visible again.** Each bullet's left-margin grip is now a full-height
  coral rail you can see at rest, brightening on hover and turning solid when the bullet is selected —
  matching the approved design instead of a near-invisible sliver. Reader UI only; no change to what the
  brief says.

## [0.25.2] - 2026-07-04

A cleaner way to open the Daily Brief in Claude.

### Changed
- **One "Open in Claude" control, not two.** The brief reader had two overlapping ways to start a Claude
  session — a whole-brief button and a separate bar for selected bullets. They're now a single top-right
  control: with nothing selected it opens the whole brief; select one or more bullets (grab the grip in the
  left margin) and it becomes "Open N in Claude" with a quick way to clear. The separate selection bar is
  gone.
- **Easier to grab a bullet.** The selection grip now spans the full height of a bullet and the whole
  left-margin gutter is clickable, so picking a point is a bigger, more forgiving target. No change to what
  the brief says or how it's built — this is reader UI only.

## [0.25.1] - 2026-07-04

A small polish to how the Daily Brief is written.

### Fixed
- **The Daily Brief no longer slips in em-dashes.** Briefs are written to avoid em/en dashes (they read as
  an AI tell), but the model occasionally used one anyway. The brief now strips em/en dashes from its own
  prose deterministically as it renders — the lead, the section headings, and every bullet — while leaving
  real article titles (which can legitimately contain a dash) untouched. A deterministic backstop under the
  existing prompt rule.

## [0.25.0] - 2026-07-04

The Daily Brief reads better, links reliably, and you can start a Claude session from any bullet.

### Fixed
- **Brief bullets link to their cards again — every bullet, every time.** A brittle citation format meant
  the model sometimes wrote a reference the brief couldn't resolve, so a whole day's bullets could render
  with no card links and no "Related" items at all. The brief now accepts either citation form and, as a
  backstop, pauses (rather than saving a link-less brief) if a featured brief somehow ends up with no
  resolvable reference. Verified on a real brief that previously showed zero linked bullets.

### Changed
- **The Daily Brief is written to be worth reading.** Bullets are longer and more substantial (roughly
  400–500 characters), lead with what the work is and why it matters, and combine genuinely-similar
  articles into one bullet instead of one per paper. The opening overview is a fuller summary of the day's
  threads, and the writing avoids the usual AI tells. Every featured article is referenced at least once.
- **Big days stay readable.** When a lot clears the relevance bar, the brief gives a full write-up to the
  top 30 items and lists the rest under "Also noticed" — nothing is dropped, and the narrative stays
  focused. (A recompose no longer un-caps that split.)

### Added
- **Open a Claude session straight from a brief bullet.** Grab the grip beside any bullet (or several) and
  an "Open in Claude" action appears. A small popover lets you combine the selection into one session or
  spin up one per bullet, review the cards that will be loaded (and drop any "related" ones you don't
  want), and see the seeded prompt before you launch.

### Notes
- Under the hood: the brief's reference token is one shared pattern (drives both link substitution and the
  per-bullet Related line); the compose prompt was rewritten for citation, coverage, length, and voice; a
  featured cap spills overflow to the tail at both compose and recompose; and the frontend parses each
  bullet's card ids from the reliable inline `card:` links (no brief-model change). Backend 713 tests /
  95.78%; frontend 390.

## [0.24.0] - 2026-07-04

Search finds titles and sources, and you can see what you've rated.

### Fixed
- **Search now finds cards by title and source, not just stored text.** A card that had full text
  stored (e.g. a YouTube card with a transcript) used to be searched *only* on that text — so
  searching "bio" missed a video titled "BIO26 Healthcare special address". Search now matches the
  title, summary, source, and link of every card, and multi-word queries like "bio youtube" work
  (each word can match a different field).
- **You can see which cards you've rated.** A thumbed card now shows a clear filled thumb — green for
  up, red for down — on the thumb control (reader and the row's action menu) *and* as a small
  persistent marker on the list row, so you know at a glance what you've already rated.

## [0.23.0] - 2026-07-04

Faster dashboard, instant thumbs, fuller summaries.

### Changed
- **The Workspace loads faster as your library grows.** The article list no longer downloads every
  card's full summary up front — it sends just enough for the two-line preview and fetches the full
  summary when you open a card. The list looks exactly the same; the payload is a fraction of the size
  and is served pre-built, so opening a large corpus is noticeably quicker.
- **Thumbs up/down feel instant.** Rating a card now updates that card in place immediately (relevance
  dot and "you set" included) instead of blanking and reloading the whole list. The ripple to similar
  articles still happens, but quietly in the background — and rapid thumbing is coalesced into a single
  refresh.
- **Fuller reader summaries.** Newly fetched articles now get a ~350–400-character summary (up to ~450),
  so the reader's Summary panel conveys the core finding and why it matters. Existing cards keep their
  current summaries.

### Notes
- Under the hood: `GET /api/cards` returns a lean list row; a new `GET /api/cards/{id}` serves the full
  card for the reader; the thumb endpoint returns the full updated card so the client merges it in place.
  No settings or workflow changes.

## [0.22.0] - 2026-07-03

Video transcripts "just work" — auto-find the yt-transcribe CLI.

### Changed
- **No more PATH fiddling for video transcripts.** Spyglass now locates the `yt-transcribe` tool
  automatically: it reuses the path you set in the YouTube Transcribe plugin, then checks your PATH,
  then the usual install spots (`~/.local/bin`, the uv tools dir). So the reliable transcript path
  (0.21.0) works even when the tool isn't on the service's PATH — no env var needed.

### Added
- **Settings → Integrations → "yt-transcribe CLI path".** An optional override; leave it blank to
  auto-detect. Changing it applies immediately (no restart).

## [0.21.0] - 2026-07-03

Reliable YouTube transcripts.

### Changed
- **"Fetch full text" on a video now gets a reliable transcript.** For YouTube links, Spyglass hands
  off to the `yt-transcribe` tool (captions, with an AssemblyAI fallback) instead of the flaky
  built-in caption library, then stores the transcript in Spyglass itself — never the vault — so it
  flows through the normal summary/relevance/embedding pipeline like any other full text. If
  `yt-transcribe` isn't installed, it quietly falls back to the previous built-in method.

### Notes
- `yt-transcribe` is an **external tool Spyglass calls**, not bundled — keep it installed (it powers
  the reliable path; the fallback covers its absence). Point Spyglass at a non-PATH install with the
  `SPYGLASS_YT_TRANSCRIBE_CMD` environment variable. Requires `yt-transcribe` ≥ 0.11.0 (the
  `--no-save` mode).

## [0.20.0] - 2026-07-03

User-owned categories, second step — sort the Unsorted backlog.

### Added
- **Recategorize, in Settings.** A new **Recategorize** button under Categories that works through
  your Unsorted pile: it files each item into one of your categories, and proposes new topical
  groups it finds. It asks the AI to read what each article is *about* (its application), so a
  clinical-LLM paper lands in Healthcare AI rather than next to other LLM papers. Items that fit no
  category are honestly left Unsorted rather than force-fit, and anything you've hand-placed is never
  touched. It runs in the background — the proposed new groups appear when it finishes, and you
  **Accept** (adds the category and files its articles) or **Discard** each.
- **A heads-up before it runs.** Because it makes one AI call per Unsorted item, a full pass can take
  several minutes and uses your OpenRouter API key — so the button confirms before starting and the
  section says so.

### Changed
- **How the backlog gets sorted.** Calibrating on the real library showed that the embedding model —
  excellent at "find similar articles" — can't reliably tell your *categories* apart: they're
  defined by application/intent, which cuts across raw topical similarity. So the sorting is done by
  the same AI classifier that already files new items (constrained to exactly your category set),
  applied to the backlog over each item's existing summary (no re-fetch). New and old items are now
  categorized the same way.

_Known trade-off: because the AI does the filing, adding or renaming a category means
re-running Recategorize to propagate it — there's no cheap one-click re-shuffle. Noted for a future
hybrid._

## [0.19.0] - 2026-07-03

User-owned categories, first step — stop category drift.

### Added
- **Manage your categories in Settings.** A new **Categories** section: a small chip list you own,
  with **+** to add and **×** to remove (removing one re-buckets its items to Unsorted, with a
  confirm). This set is the whole vocabulary — the AI never invents new labels.
- **One-time consolidation on first launch.** On the first start of this version, your drifted
  labels ("AI in Healthcare" / "Healthcare AI" / "AI in Surgery" / …) fold into six broad buckets —
  **Healthcare AI · LLMs & AI Research · Agentic Systems · AI Dev Tools & Skills · Robotics ·
  Product & Career** — and "Misc" goes to Unsorted. It runs exactly once and never re-seeds, so a
  bucket you later remove stays removed.

### Changed
- **Enrichment can no longer coin near-duplicate categories.** The background LLM call is now
  constrained to your managed set (a schema enum, with a server-side backstop that maps any stray
  label to Unsorted). Fine-grained distinctions live in tags, not new categories. With no categories
  configured, behaviour is unchanged (free-text) for back-compat.

_Not yet: the ~1,950 Unsorted items are assigned by the Recategorize clustering pass (the second step)._

## [0.18.0] - 2026-07-03

Smart session start + NotebookLM grounding, plus a
bullet-structured Daily Brief with inline related items.

### Added
- **Context-aware session menu, owned by the skill.** The dashboard "Open in Claude"
  launcher now sends a thin *pointer* prompt; the `spyglass` skill's session-menu workflow builds
  the menu from live context (selection, review queue, latest brief, NotebookLM availability) and
  shows only the options that apply — so menu changes are a skill edit, not a service release. The
  Daily Brief ("work with today's brief") finally appears as an option now that briefs are
  reachable over MCP.
- **`get_brief` MCP tool.** Exposes the latest Daily Brief (or one by id) as markdown plus
  the articles it references (`card_id`, `title`, `url`); returns an explicit error when there are
  no briefs. Powers brief work and the NotebookLM push.
- **Startup skill sync.** On service start, the repo's bundled `skills/*/SKILL.md` are
  mirrored into the vault's `.claude/skills/` (one-way, copy-on-diff, non-fatal), so a
  dashboard-launched session always loads the current instructions instead of a stale hand-copied
  snapshot.
- **NotebookLM from Spyglass.** With the user-scope `notebooklm` MCP connected, the session
  menu offers pushing the selection, today's brief, or a category into a Google NotebookLM notebook
  (article URLs preferred, stored full text as fallback) and running grounded, citation-backed Q&A.
  The reusable mechanics live in a NotebookLM grounding skill; `mcp__notebooklm` is added
  to the spawned-session tool allowlist.
- **Inline related items under each brief bullet.** Every brief bullet now carries a muted,
  clickable "Related:" sub-line surfacing the nearest *judged, non-out* corpus cards to that
  bullet's articles — excluding anything already in the brief, capped and section-deduped, so a
  curated brief never resurfaces rejected or unjudged work. Backend-only; the frontend renders the
  nested list natively.

### Changed
- **The Daily Brief reads as grouped bullets, not prose.** Each thematic section is now a
  set of grouped multi-sentence bullets instead of one prose body (schema `{heading, bullets: […]}`):
  the prompt groups only genuinely-related articles into a bullet (one or several; unrelated work
  gets its own), each bullet 2–4 sentences leading with substance then significance, in a plain
  human voice with the usual AI tells banned. The renderer emits one `- ` item per bullet, with
  `[#n]` → card-link substitution across the lead and every bullet; malformed output pauses like any
  other LLM failure, and Recompose rebuilds an existing brief in place. The grouping prompt further
  **prefers combining** related articles into one bullet rather than splitting.

## [0.17.0] - 2026-07-03

The first post-MVP UX release: a readable brief, add any page by URL, and explore similar articles.

### Added
- **Add a webpage directly.** A **+ Add page** control in the Workspace toolbar: paste any
  URL and Spyglass creates a card, fetches the full text (the GitHub-README path included), and runs
  the same summary + relevance enrichment as your feeds — so a manually added page joins the next
  Daily Brief like anything collected. Re-adding a page opens the existing card instead of duplicating.
- **Explore similar articles.** An **Explore similar** action on every card (row and reader)
  switches the list into an explore view — a "Similar to: …" banner over the article's semantic
  neighbourhood, each row tagged with a similarity score, ranked closest-first. Exit restores your
  feed with its filters intact. Alongside it, a **Research on the web** action opens a Claude session
  briefed to find *new* related articles and file the best ones back through Add page.

### Changed
- **The Daily Brief reads like a briefing.** The narrative is now composed as a short lead
  plus titled thematic sections instead of one unbroken block, so a heavy day scans in seconds. The
  References and "Also noticed" lists became collapsible panels (References open, Also-noticed
  collapsed with its count). A **Recompose** button re-runs today's brief in place — the same
  articles, freshly written — without waiting for tomorrow.

## [0.16.0] - 2026-07-02

**The MVP loop is complete**: control sources → collect → filter noise → **read one
generated Daily Brief** → open any referenced article in-app → chat with Claude about it.

### Added
- **Daily Brief.** A new **Brief tab** (first in the nav) holds one generated digest per
  day. After the daily judging pass, a background job composes every not-yet-briefed article
  collected in the window (~24h, chained brief-to-brief, capped at 72h): items judged
  medium-and-up get a thematic LLM-written narrative (one cheap OpenRouter call) with every
  article linked; low-relevance items appear in a compact "Also noticed" list; out/unjudged are
  excluded (unjudged stay eligible for the next brief). References carry the source, published
  date, relevance level, and **semantic backlinks** — embedding-nearest neighbours among
  previously briefed articles, so today's story points to the coverage it continues.
- **In-app references.** Clicking any article in a brief opens that card in the Workspace
  reader (clearing any hiding filter so the article always appears). **Send to Claude** on a
  brief seeds a session with the brief's articles.
- **Generate now.** A manual button composes the pending window on demand, with honest
  outcomes: "Nothing new to brief" when nothing is eligible, and a clear paused message when
  the LLM is unreachable — no degraded briefs are ever written; held items are covered by the
  next successful run, and no article ever appears in two briefs.

### Fixed
- **Articles with malformed characters can be stored again.** Fetched text containing
  unpaired surrogates crashed storage, leaving such cards permanently unjudged (and unbriefable);
  text is now sanitized before storing. Verified against the affected card.
- Brief timestamps are serialized with an explicit UTC marker so displayed windows don't shift
  by the local timezone offset.

## [0.15.5] - 2026-07-02

### Added
- **Article dates on cards.** Every list row and the reader header now show when the
  article was published — relative for the first week ("3h ago", "2d ago"), then absolute
  ("Jun 12", with the year when older), full timestamp on hover. Falls back to the collected
  date (and says so) if a source ever omits a publish date.
- **List sort toggle.** A "Sort" dropdown in the filter bar: **Newest arrivals**
  (collection order, the default and previous behavior) or **Recently published** (article
  date). The choice persists across reloads; search results keep their relevance ranking.
- **"Out only" relevance filter.** A new option in the Relevance dropdown that shows
  only items the relevance model marked out — so the rejected pile (1000+ cards) can finally be
  reviewed for false negatives, where a rescuing thumb-up teaches the feedback model the most.

## [0.15.4] - 2026-07-02

### Fixed
- **Manual "Fetch full text" is now reliable end-to-end.** An explicit fetch
  skips the Gate-1 LLM call entirely (0.15.3 bypassed the *cutoff* but still ran the call, so a
  missing/unreachable OpenRouter key 500'd before fetching), and a Gate-2 enrichment failure is
  non-fatal — the article text is stored and readable even when the LLM is down. GitHub repo
  pages now fetch the **README as raw markdown** instead of scraping the app shell (which has no
  extractable prose); `/blob/`, `/tree/`, and non-repo GitHub URLs still use the generic
  extractor. Live-verified against real cards, including an invalid-key probe.
- **Card list and reader pane scroll correctly at any zoom.** Both reported
  symptoms — cards disappearing mid-scroll with the bottom unreachable, and articles that
  couldn't scroll to the end — were the app's CSS zoom breaking viewport coordinate math. The
  card list now owns its **own scrollbar** (element-scroll virtualization; the page no longer
  drives the list), and pane heights are zoom-corrected via a published `--app-zoom-inv` factor.
  Verified at 70–150% zoom.
- **Relevance filter switches are visibly correct.** The level filters are floors by
  design ("Low" keeps everything low *and up*), which read as stale results; the labels now say
  **"Medium & up" / "Low & up"**, and changing any filter or category jumps the list back to the
  top instead of stranding the viewport mid-list.

### Changed
- Facet dropdown values are memoized instead of re-derived from the full corpus on every render.

## [0.15.3] - 2026-07-01

### Fixed
- **"Fetch full text" now always fetches when you click it.** The button ran the enrichment
  cascade's Gate-1 relevance check first and *silently skipped the fetch* for any article the LLM
  scored below your relevance gate — so deliberately opening a lower-scored article (e.g. an
  Anthropic research page that scored 33/100) fetched nothing and the button just re-appeared. An
  explicit fetch now **bypasses that gate** and always downloads + stores the full text; the gate
  still cost-controls the automatic daily pass. (Surfacing a clear
  message when a page genuinely has no extractable text is a separate issue.)

## [0.15.2] - 2026-07-01

### Added
- **"Restart service" in the plugin** — a command ("Spyglass: Restart service") and a button in the
  plugin settings that stop and restart the Python service, which reloads new backend code from the
  repo. Uses the service's own `/api/shutdown` endpoint, so it works even when the running service was
  started in an earlier session, and waits for it to fully stop before respawning. This is now the
  one-click way to pick up an update — no more hunting for the port. No-op in connect-only mode.

## [0.15.1] - 2026-07-01

Post-0.15.0 fixes and small quality-of-life additions, from live testing of the relevance filter.

### Fixed
- **Relevance filter no longer blanks the list against an older backend.** The dashboard now falls
  back to the stored relevance bucket when the service hasn't sent the new blended `effective_relevance`
  field yet (e.g. mid-upgrade), so High/Medium/Low can't silently hide everything.
- **The filter "Clear" button now also resets the relevance filter** back to "All" (it previously reset
  only the source/category/tag facets, so a level filter kept hiding rows).
- **Feeds tab item-counts are correct again.** Items collected before 0.13.0 had no stored feed URL and
  were undercounted per feed; a one-time startup backfill re-attributes them from the reader's own
  entry→feed mapping (idempotent, guarded, and it snapshots the DB first).
- **`/api/health` now reports the real version** instead of a stale hardcoded value, so you can confirm
  which build is actually running.

### Added
- **Persistent dashboard zoom.** A small "− 100% +" control in the header scales the whole dashboard and
  remembers the setting across reloads (the web view can't capture native browser zoom, so this is an
  app-level zoom).

### Changed
- **The "Feed note" setting is relabelled "Feed note (import only)"** with a note that feeds are now
  managed in the Feeds tab — it remains available for one-off import. The interest-note and
  preferences-note settings are unchanged.

### Notes
- Backend (the Spyglass service) + dashboard frontend; the Obsidian plugin shell is unchanged. The UI
  reaches the dashboard via the repo's `frontend/dist` build, and the service runs from the repo.

## [0.15.0] - 2026-07-01

Relevance filter v2: your thumbs now steer relevance
immediately and propagate to semantically-similar articles -- no trained classifier required.

### Added
- **Layered relevance feedback.** A thumb changes the article's displayed relevance at once and
  ripples to its neighbours. **Thumb-down is a decisive "out"** -- it hides the article and pushes
  semantically-similar ones down too (reversible: clear the thumb to restore it). **Thumb-up is a
  soft boost** -- it lifts the article and its neighbours without pinning a fixed level.
- **Blended relevance for everything else.** An unthumbed article's level is the LLM relevance
  score nudged by a similarity-weighted vote from your thumbed articles. Propagation runs over the
  article embeddings only (never tags or the summary text), and degrades gracefully to the LLM
  score when you have few thumbs.
- **"Unjudged" filter option.** The relevance filter now offers `All | Unjudged | High | Medium |
  Low`; "Unjudged" surfaces articles the AI pass has not scored yet.
- **Editable relevance override.** Set an article's relevance by hand (High/Med/Low/Out) or **Clear**
  it to fall back to the blended value -- an editable, reversible escape hatch.
- **New items judged on refresh.** A refresh that brings in new articles now scores them
  right away instead of leaving them unjudged until the next restart.

### Changed
- **The relevance filter HIDES filtered-out articles** (previously it only dimmed them), and a thumb
  re-ranks the list immediately so the correction is visible.

### Notes
- Backend (the Spyglass service) + dashboard frontend; the Obsidian plugin shell is unchanged, so
  this is a version-coherence marker -- the UI reaches the dashboard via the repo's `frontend/dist`
  build (rebuild + reload), and the service runs from the repo.

## [0.14.0] - 2026-07-01

Reader and card UI refinements: the article view and the card
list get a cleaner, richer read.

### Added
- **Collapsible article Summary panel.** The enriched summary now sits at the top of the
  reader in a "Summary" disclosure, open by default, rendered as rich Markdown (bold, lists, links).
  Un-enriched RSS summaries (still HTML) are shown as clean plain text, not literal tags.
- **Slide-out row action toolbar.** Each card's actions are tucked into a drawer pinned to the row's
  right edge behind a small arrow handle; hover or keyboard focus slides them out. The toolbar no
  longer reserves horizontal space, so titles use the full card width.
- **Subtle card elevation.** List rows carry a faint resting shadow and a gentle lift on hover.

### Changed
- **Shared Markdown renderer.** The reader body, the new summary panel, and the briefing modal now
  render Markdown through one component (react-markdown + remark-gfm, no raw HTML). The briefing's
  prose is now properly styled (headings, margins, bullets) via the shared reader styles.

### Notes
- Frontend-only; the plugin shell is unchanged, so this release is a version-coherence marker -- the
  UI reaches the dashboard via the repo's `frontend/dist` build, not the BRAT plugin asset.

## [0.13.1] - 2026-06-30

Feeds discovery hardening, from the 0.13.0 live smoke.

### Added
- **Honest discovery failure reasons.** When discovery cannot read a page, the panel now says *why* --
  "this site blocked automated access" (e.g. a Cloudflare challenge) versus "no feeds found on this
  page" -- instead of one generic message.
- **One-click Google News fallback.** When a site is blocked, the discovery panel offers "Subscribe via
  Google News" (optional topic + the site prefilled): it builds an open Google News search RSS feed and
  adds it, so a bot-protected site is no longer a dead end. Spyglass's relevance filter then narrows it.
- **Editable feed name at add-time.** The add flows accept an optional display name (`POST /api/feeds`
  now takes `{url, name?}`), so an aggregator feed's auto-title (e.g. `"query" - Google News`) can be
  replaced with something readable on the spot. Post-add inline rename is unchanged.

### Notes
- Not a Cloudflare-bypass / headless-browser effort (an explicit non-goal); blocked sites are handled by the
  Google News route. Lenient parsing of malformed feeds is deferred.

## [0.13.0] - 2026-06-30

Feeds tab: the RSS subscription set becomes a visible,
named, health-surfaced, directly controllable registry, and "adding a site" resolves its
feeds through in-service tiered discovery.

### Added
- A new **Feeds** tab listing every feed with its name, URL, fetch health (ok/error +
  timestamp), and item count. Inline rename, one-click enable/disable, and a confirmed
  delete.
- A **DB-backed feed registry** is now the source of truth for which RSS feeds are
  collected. Collection builds from enabled registry rows; each item carries a stable
  `feed_url` joining it back to its feed.
- **Per-feed health write-back**: after every refresh, each feed's fetch outcome (ok /
  error + reason + timestamp) is written to its row, so a dead or wrong feed shows as
  unhealthy instead of failing silently.
- **Add-by-URL + tiered discovery**: paste a feed URL to add it directly; paste a site
  homepage and Spyglass finds its declared feeds (shallow), with a "Search deeper" pass
  that probes common paths and crawls one level of section links. Discovery is
  user-initiated and bounded (one page, one level, capped links/bytes, per-host timeout) --
  never background scraping.
- **OPML + markdown import/export**: import a feed list (OPML or the legacy markdown note)
  and export the registry as OPML or markdown -- no lock-in.
- New REST surface under `/api/feeds` (list/add/update/delete, discover, import, export)
  and a disabled-feed display filter on `/api/cards`.

### Changed
- The hand-edited vault feed note is no longer the canonical subscription source. It is
  imported once into the registry on first run and otherwise survives only as an
  import source (`SPYGLASS_FEED_NOTE_PATH`).

### Security
- OPML import parses untrusted XML with `defusedxml` (hardened against XXE and entity-
  expansion attacks). HTML discovery uses the stdlib `html.parser` backend (no XML
  external-entity surface).

## [0.12.0] - 2026-06-29

Refactor "trim pass": removes de-scoped surfaces ahead of the MVP rework. Database
schema is preserved (no migration) -- removed features leave their tables/columns dormant.

### Added
- Background auto-categorization (from the post-0.11.0 embedding work): after each embedding
  pass, confident uncategorized cards are assigned to their nearest category centroid in the
  background (no Claude). Ambiguous/low-similarity items are left uncategorized.

### Changed
- Window mode collapsed to a single chromeless browser app window (with an Obsidian popout
  fallback). The three-way window-mode setting (tab / Obsidian window / browser app) is removed.

### Removed
- In-app reader highlights and per-card notes: UI and HTTP endpoints removed.
  The `Highlight` table and `Card.note` column are kept dormant (no data loss).
- Category chip drag-to-reorder / pinning, including the `PUT /api/categories/order`
  endpoint. The `Category.position` column is kept dormant.
- The in-dashboard "Needs Review" category-review surface (chip, tentative/outlier markers,
  quick-assign). The categorization engine and its backend endpoints remain (de-emphasized).

## [0.11.0] - 2026-06-28
- Deep (chunked) body embeddings -- the second step of the local embedding work: once an item's full text is
  stored, a background pass upgrades it to a whole-body embedding (chunked and mean-pooled),
  improving "Similar articles" quality for full-text items.

## [0.10.0] - 2026-06-28
- Self-contained `~/.spyglass` storage (DB, backups, models) out of any cloud-synced folder,
  configurable via `SPYGLASS_DATA_DIR`; first-run migration from `%LOCALAPPDATA%\Spyglass`;
  startup integrity check with degraded `/api/health` and rotating consistent backups; plugin
  background auto-refresh on a timer.

## [0.9.0] - 2026-06-28
- Local embedding substrate: background embeddings (arctic-embed-s via FastEmbed, CPU-only) and
  a reader "Similar articles" panel ranking the nearest items by semantic similarity.

## [0.7.2] - 2026-06-27
- Thumbs pop animation on select.

## [0.7.1] - 2026-06-26
- Fix card-list virtualization for large feeds.

## [0.7.0] - 2026-06-26
- Article feedback (thumbs up/down) feeding the preference-learning loop.

## [0.6.0] - 2026-06-26
- Per-item actions, delete lifecycle, open-in-browser, and UX backlog items.

## [0.5.0] - 2026-06-12
- Release pipeline fix (use `npm install` so CI accepts the lockfile).

## [0.4.0] - 2026-06-11
- Filters, groups, curation setup, and a configurable research folder.

## [0.3.0] - 2026-06-11
- Interactive cards for all collected items.

## [0.2.0] - 2026-06-11
- Show uncurated items in the dashboard; default to iframe embedding.

## [0.1.0] - 2026-06-11
- BRAT-installable plugin: root `manifest.json`, `versions.json`, and the release workflow.

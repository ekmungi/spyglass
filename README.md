# Spyglass

**A personal research dashboard that works alongside Obsidian.** Spyglass watches the sources you
care about, filters the noise and summarizes what is left against your own interest profile, and
gives you a focused two-pane workspace to read, triage, and turn the keepers into briefings saved in
your vault. A local Python service does the collecting, storing, and semantic work; Claude makes the
judgment calls; and your data stays on your machine, apart from the requests listed under
[Data, storage, and privacy](#data-storage-and-privacy).

The goal is a single place where the day's reading arrives already triaged -- named, summarized,
scored for relevance, grouped, and searchable -- so the only thing left for you to do is the part
that actually needs a human: deciding what matters and thinking about it.

**Status.** Spyglass is a one-person project, built for and tested on Windows 11. It is used daily,
but expect rough edges. Issues and pull requests are welcome.

## Requirements

| What | Needed for | Required? |
|------|------------|-----------|
| Windows 10 or 11 | The Obsidian plugin starts the service with the repository's `.venv\Scripts\python.exe`. On macOS or Linux, start the service yourself and turn on the plugin's *Connect only* setting (untested). | Tested platform |
| [uv](https://docs.astral.sh/uv/) and Python 3.12+ | The service | Yes |
| [Node.js](https://nodejs.org/) 20.19+ or 22.12+ | Building the dashboard (and the plugin, if you build it yourself) | Yes |
| [Obsidian](https://obsidian.md/) with the Spyglass plugin | Opening the dashboard window and starting the service for you; briefings and notes land in your vault | Recommended |
| An [OpenRouter](https://openrouter.ai/) API key | Relevance scoring and the short summary of each new item | Recommended; without it, collection and search still work |
| The [Claude desktop app](https://claude.ai/download) | The linked Claude session, curation, deep dives, and the paper inbox | Recommended |
| [Claude Code](https://docs.claude.com/en/docs/claude-code) on your PATH | Background jobs (*Prepare detail*, *File it*) | Optional |
| A [Raindrop.io](https://raindrop.io/) test token | Collecting your Raindrop bookmarks | Optional |
| The Slack connector in Claude desktop | The paper inbox | Optional |

## Install

1. **Get the code and the Python environment.**

   ```
   git clone https://github.com/ekmungi/spyglass.git
   cd spyglass
   uv sync
   ```

2. **Configure.** Copy `.env.example` to `.env` and fill in what you use: your OpenRouter key and,
   optionally, a Raindrop token. The vault path is only needed when you run the service without
   Obsidian; the plugin passes your vault's path to the service itself. To enable the local-browser
   fetch tier (the last-resort renderer for JavaScript-heavy or bot-walled pages), run the one-time
   `uv run patchright install chromium`; skip it and that single tier is skipped gracefully.

3. **Build the dashboard once:** `cd frontend && npm install && npm run build`.

4. **Install the Obsidian plugin**, one of two ways:
   - **BRAT (recommended):** install the BRAT community plugin, then "Add beta plugin" with
     `ekmungi/spyglass`. BRAT installs the latest release and keeps it updated.
   - **Manual:** `cd plugin && npm install && npm run build`, then copy `plugin/dist/main.js` and
     `plugin/dist/manifest.json` into `<vault>/.obsidian/plugins/spyglass/` and enable the plugin.

   Then open the plugin's settings and set **Service repository path** to the folder you cloned
   into (the plugin reminds you until it is set). The ribbon telescope opens the dashboard in its
   own window and starts the service automatically.

5. **Claude.** Install the Claude desktop app and sign in. Nothing else to copy: when the service
   starts it syncs the bundled skills into `<vault>/.claude/skills/` and adds the `spyglass` MCP
   server to `<vault>/.mcp.json` (keeping any other servers; set `SPYGLASS_REGISTER_MCP=false` to
   manage that file yourself).

**Manual service run (no Obsidian):** `uv run python -m spyglass_service`, then open
`http://localhost:7777/`. The service answers only requests addressed to `127.0.0.1` or
`localhost`, so another web page cannot read it by pointing its own domain at your computer. A
request that changes something is refused when the browser says it comes from another site.

**Default folders.** Spyglass writes into your vault under `03 RESOURCES/` by default: briefings
go to the plugin's *Research folder* setting (`03 RESOURCES/Research/Spyglass`) and detail notes to
the dashboard's *Detail notes folder* setting (`03 RESOURCES/Spyglass/Brief notes`). Point them
wherever suits your vault.

## How it works

Spyglass is a pipeline from raw sources to worked knowledge. Each stage is incremental and
failure-isolated, so a single dead feed or a slow fetch never blocks the rest.

1. **Collect.** A local service pulls new items from your configured sources -- RSS/Atom feeds and
   Raindrop bookmarks today, anything via a pluggable collector interface. RSS subscriptions are
   driven by a DB-backed feed registry you manage from the Feeds tab.
2. **Store.** Each item's full text is fetched and stored as clean markdown in SQLite, indexed for
   full-text search (FTS5). Collected items become interactive cards immediately, before any AI runs.
3. **Curate.** In a vault-rooted Claude session (or one tap in the dashboard), Claude enriches
   each card with a summary and tags, and assigns a category.
4. **Score relevance.** A relevance pass rates each item against an editable interest profile. Your
   overrides follow a net-change rule and feed a preference-learning skill, so the filter gets more
   like you over time. A one-tap thumbs up/down records a holistic verdict that feeds the same loop.
5. **Read and work.** A two-pane research workspace (list + full-text reader) lets you triage,
   filter, search, and act on items. Deep dives produce markdown briefings written straight into
   your Obsidian vault.
6. **Learn, locally.** A background pass embeds every article on-device. Those embeddings power a
   "Similar articles" panel and background auto-categorization -- no GPU, no Claude, no network.

## Features

### Sources and the Feeds tab
- A dedicated **Feeds** tab is the home for your RSS subscriptions, backed by a database feed
  registry that is the single source of truth for what gets collected (the old hand-edited vault
  note is now only a one-time import source).
- Every feed shows its name, **fetch health** (a dead or misconfigured feed surfaces as unhealthy
  with a reason and timestamp instead of failing silently), and a live item count.
- Inline rename (the name you set becomes the source label on that feed's cards), one-click
  **enable/disable** (a reversible display filter that keeps collecting underneath), and a
  confirmed delete that also stops re-collection.
- **Add by URL, or discover.** Paste a feed URL to add it directly; paste a site homepage and
  Spyglass runs in-service tiered discovery -- declared feeds instantly, then a bounded "search
  deeper" pass that probes common paths and crawls one level of section links. Discovery is
  user-initiated and bounded (one page, one level, capped links and bytes, per-host timeout); it is
  never a background scraper. When a site blocks automated access (e.g. a Cloudflare challenge),
  discovery says so plainly and offers a one-click **"Subscribe via Google News"** fallback -- it builds
  an open, well-formed Google News search feed (optionally scoped to that site) so a bot-protected
  source is never a dead end. You can also set a friendly feed name as you add.
- **No lock-in:** import and export your whole feed list as OPML or markdown.

### Curation, relevance, and preference learning
- Each item gets a summary, tags, and a managed category.
- A relevance pass scores items against your interest profile; manual overrides use a net-change
  rule so only genuine corrections become a learning signal.
- Thumbs up/down on any item records a separate holistic verdict. Both signals feed the
  `spyglass-preferences` skill, which consolidates your overrides back into the profile.

### Reading workspace
- A two-pane layout: a virtualized item list beside a full-text reader, with segmented-control
  chrome, a multi-select selection bar, and an icon-first reader toolbar.
- Full-text search over stored markdown (FTS5), category and relevance filters, and per-item
  actions (open externally, delete, send to a Claude session).

### Resilient full-text fetching
- Reading the page behind a link uses a tiered ladder that escalates only when a step fails: a
  plain fetch, then a browser-TLS-fingerprint fetch (`curl_cffi`), then a reader service that
  renders the page server-side ([Jina Reader](https://jina.ai/reader)), then a local headless
  browser ([`patchright`](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright) + Chromium) as a
  last resort. HTML uses the full ladder; PDFs and images skip the browser tier. The winning
  method is cached per domain, so the automatic pass pays the escalation cost once per site.
- The reader and browser tiers are each a setting (both on by default). Turn them off to keep
  every fetch fully local; note that the reader tier sends the failing page's URL to jina.ai.
- PDFs are extracted with **PyMuPDF** (`fitz`); a ~25 MB download cap guards against a mislabeled
  giant file. When every tier fails, the reader shows a legible reason (which tier, what status)
  instead of a bare "failed".
- **On-demand fetches run as background jobs.** "Fetch full text" queues the work on a serial
  worker inside the service and returns immediately, so the ladder's slow tiers never run
  inside the HTTP request. Progress lives in the database, not the reader pane: it survives
  opening another card, closing the reader, and reloading the dashboard, and in-flight cards are
  marked in the list. Clicking twice queues one fetch, not two, and a fetch interrupted by a
  service restart is reported as such rather than left spinning.

### Semantic find-similar and auto-categorization
- Every article is embedded locally with **arctic-embed-s** via FastEmbed (ONNX Runtime, CPU-only --
  no torch, no GPU, no Claude).
- Embedding is **two-tier**: every item gets a shallow embedding (title + summary) immediately, and
  once its full text is stored a background pass upgrades it to a deep embedding of the whole body
  (chunked to the model's token budget and mean-pooled into one vector). Both tiers share one model,
  so there is no extra dependency or download.
- The reader's **Similar articles** panel ranks the nearest items by semantic similarity. The same
  embeddings drive background auto-categorization: confident uncategorized cards are assigned to
  their nearest per-category centroid (computed from your confirmed cards); ambiguous and
  low-similarity items are left for you to decide.

### Deep dives and the vault
- Turn a card into a deep-dive briefing; Claude writes a markdown briefing into your Obsidian vault,
  where it becomes a first-class, linkable note alongside the rest of your knowledge.

## Working with Claude

**One linked Claude session.** The header shows whether a Claude session is linked to Spyglass.
Its button opens a new session in the **Code tab of the Claude desktop app**, in the vault, with a
link code typed in; press Enter and the session links itself. Only one session is linked at a time:
opening another moves the link, and the earlier session is told it is no longer linked. In the
linked session, point at items by their code (`#1042`, shown on every item and copied with one
click), by "this one" (the item open in the reader) or "these" (the ticked items). (Spyglass also
offers its items to Claude's @ list, but the desktop app's Code tab lists only files and folders
there; @ items show up in Claude in a terminal.) The other Claude buttons (the selection bar, Send
to Claude, Research on the web, the row icons and the brief's Open in Claude) talk to that session:
with one linked, they select the items and copy the request for you to paste there; with none, they
open a new linked session with it. Nothing opens in a terminal. The first session asks once to
approve the `spyglass` server and its tools. If the desktop app cannot be opened, the dashboard
offers to copy the request instead.

**Ending the link.** The header's unlink button ends it, and it also ends about a minute and a half
after the last Spyglass window closes (a reload or a second window keeps it). The Claude window
stays open, but its next call to Spyglass is refused with the reason, and the header says why there
is no link.

**Folder and environment.** A link can name the folder but not the environment: a new session uses
whatever Claude desktop's environment picker shows, so set it to this computer (Local) once. Claude
always asks you to confirm a link's folder. A Claude desktop bug can still start the session in an
empty scratch folder while the folder chip shows the vault; Spyglass spells the folder differently
on each link to avoid it. If it happens anyway, the new session says so and asks you to start a
session with the vault picked, and after a minute and a half the header tells you the session has
not linked.

Limits: Spyglass cannot type into a Claude session or close one. A linked session that has been
silent for six hours shows as idle, and the next conversation opens a new linked session. If Claude
desktop reconnects a session or you resume an old conversation, Spyglass sees a new connection and
cannot tell it is the same conversation, so open a new linked session from Spyglass. Item codes and
"this one" always reflect what Spyglass shows now.

### Detailed notes in the background

In the reader, **Prepare detail** asks Claude to write a detailed note for the item. **File it**
asks Claude to file that note in your vault and say where and why. Both run as hidden Claude Code
runs (`claude -p`, no window), one at a time; the reader shows what the job is doing, can cancel it,
and shows Claude's reason if it fails, with Try again.

- **Prepare detail** reads the item's stored text, your interests and preferences, and your vault
  map's projects and areas, then writes a note: the bottom line, key points, why it matters to you,
  limits and confidence, and links to related notes. Spyglass writes the file itself in
  `03 RESOURCES/Spyglass/Brief notes/<date>/` (Settings: *Detail notes folder*).
- **File it** reads `vault-map.md` at the vault root if you keep one (a note whose table says what
  each folder is for); otherwise it looks at your top-level folders. It picks the folder, and
  Spyglass then moves the note itself with your Obsidian MCP server's `vault_move` (default server
  name `obsidian-vault`), so links to the note, and comments attached to the note by plugins that
  follow renames, move with it. The run only names the folder, so text in an article cannot make it
  move or change any other note. Spyglass refuses a folder outside the vault, a hidden folder, the
  vault's top folder, Spyglass's own folders (Brief notes, its `03 RESOURCES/Spyglass` parent, and
  the briefing and document folders) and a name already taken, and never overwrites a note. A note
  in one of Spyglass's folders, such as an older briefing, counts as not filed yet and can be filed
  or deleted from Spyglass. If Obsidian is closed, Spyglass opens it and waits up to 90 seconds.
  Spyglass then checks that the note arrived and the old file is gone. **Move** afterwards asks your
  linked Claude session.
- **Delete note** moves an unfiled note to the vault's `.trash` and counts as a thumbs down. A filed
  note is deleted in Obsidian.
- **Read detail** shows the note in Spyglass.

**Models and your Claude limits.** Background jobs share your plan's 5-hour and weekly limits
with Claude desktop and claude.ai, and Claude Code's own default on a Max plan is Opus, which uses
them fastest. So each job names its model: Prepare detail runs on Sonnet and File it on Haiku
(Settings: *Model for Prepare detail*, *Model for File it*). After each job the reader shows how
much of your 5-hour and weekly limits is used, as Claude reports it. When Claude says a limit is
reached, the job goes back in the queue and nothing else starts until the reset time Claude gives;
the reader says when. The short summaries of new feed items stay on the cheap OpenRouter model, so
they never touch your Claude limits.

What a run may do: read and search files inside the vault (its only built-in tools are Read, Glob
and Grep) and use the Spyglass tools its job needs. Nothing else: shell, file writes, web tools,
subagents, scheduled tasks and messages to other Claude sessions are not available, and reading
outside the vault is refused. A run ignores your own and the vault's Claude settings files
(`--setting-sources ""`), so no allow rule, plugin or hook of yours widens or slows it, and it
loads only Spyglass's MCP server. Your Obsidian server is never given to a run: Spyglass uses it
itself to move a filed note, and finds it in the vault's `.mcp.json` or your `~/.claude.json`
(Settings: *Obsidian MCP server*). A run never asks for permission (`--permission-mode dontAsk`).
Runs use your Claude sign-in; an `ANTHROPIC_API_KEY` in Spyglass's environment is not passed on, so
jobs count against your plan, not an API key. Each run is limited to 10 minutes (Settings: *Job
time limit*) and 40 turns. Spyglass finds Claude Code on your PATH or in `%USERPROFILE%\.local\bin`;
set *Claude command* in Settings otherwise. Every job is listed in the Activity tab.

If a note moves without Spyglass knowing (you move it in Obsidian, or a filing run stops after
moving it), Spyglass finds it again by its `spyglass_item` property. The linked Claude session
records a move with the `set_item_note` tool.

### Paper inbox

Drop papers (arXiv links, DOIs, journal pages, PDFs) into one Slack channel, with a few words of
your own if you like. In Spyglass: Settings, *Inbox Slack channel* (for example `paper-inbox`).
Then press **Process inbox** on the Inbox tab. A Claude desktop session opens with the request
typed in; once sent, it reads the new messages through your Slack connector, files each paper in
the vault (with a paper-filing skill if you have one, see below), writes a debrief into the paper's
note and reports to Spyglass. The Inbox tab lists each paper with a short summary, **Open the
debrief** (opens the note in Obsidian) and **Discuss in Claude**, and each run's own debrief: how
that run's papers connect, link to your notes and could feed your active projects. It never posts
in Slack. To run it at set times, create a scheduled task in the Claude desktop app (Code tab,
Scheduled, New task): folder = your vault, times of your choice (for example 8:00 and 16:30),
instructions `Process my Spyglass inbox: call the spyglass tool inbox_start first and follow the
instructions it returns.` (This works whether or not the `spyglass-inbox` skill is in the vault
yet.) The first run asks once to allow the spyglass and Slack tools; choose "always allow".

**Background refresh:** the Obsidian plugin can refresh in the background on a timer (collection
only, no Claude). Enable "Auto-refresh" and set the interval (default 60 min) in the plugin settings;
a status-bar item shows the last refresh, and a "Refresh Spyglass now" command forces one.

## Optional Claude skills

Spyglass bundles three Claude skills in `skills/` (`spyglass` for curation, the relevance pass and
deep dives; `spyglass-inbox` for the paper inbox; `spyglass-preferences` for preference training)
and copies them into your vault when the service starts. A few workflows can also use tools that
Spyglass does not ship. None is required, and each has a fallback. Claude finds a skill by its
description, so any skill that does the job below is picked up; you do not need to rename it.

| Capability | Used by | What it must do | Without it |
|------------|---------|-----------------|------------|
| **A paper-filing skill** | The paper inbox, and "file it" requests in the linked session | Take a paper (a URL, a PDF or a Slack message), write a vault note with links to related notes, and report the note's path | Claude files each paper as a plain note with Spyglass's own `save_briefing` tool |
| **A NotebookLM grounding skill**, with a NotebookLM MCP server | The `spyglass` skill's NotebookLM workflow | Create a notebook from chosen sources and answer questions from it with citations | With only the MCP server, the `spyglass` skill does the steps itself; with neither, the NotebookLM steps are skipped with a message |
| **yt-transcribe** ([ekmungi/youtube-transcribe](https://github.com/ekmungi/youtube-transcribe)) | Full text of YouTube videos | A CLI that prints a video's transcript | Spyglass falls back to `youtube-transcript-api` (captions only, less reliable) |

## Architecture

- `src/spyglass_service/` -- Python service: FastAPI app, source collectors, the curation and
  relevance core, the feed registry and discovery module, the MCP server, and the vault writer.
  Managed with uv (project-local `.venv`).
- `frontend/` -- React single-page app (Vite, Tailwind v4, shadcn/ui) served by the service and
  shown in a chromeless browser app window, with an Obsidian popout fallback.
- `plugin/` -- Obsidian plugin (TypeScript): opens the dashboard window and manages the service
  lifecycle.
- `skills/` -- the bundled Claude skills (see [Optional Claude skills](#optional-claude-skills)).
- `tests/` -- Python test suite (pytest, 80 percent minimum coverage). The frontend and plugin use
  Vitest.

## Data, storage, and privacy

Operational data lives in `~/.spyglass` (the database, its rotating backups, and the embedding model
under `~/.spyglass/models`). This directory is deliberately local and non-synced: a live SQLite
database inside a cloud-synced folder will corrupt. The location is configurable via the
`SPYGLASS_DATA_DIR` environment variable or the plugin's *Data directory* setting.

On first run, an existing `%LOCALAPPDATA%\Spyglass` database is migrated into `~/.spyglass`
automatically. On startup the database is integrity-checked; a corrupt database is reported via
`/api/health` as degraded -- and a rotating consistent backup is kept -- rather than crash-looping
the service.

Local embeddings download the arctic-embed-s model (~130 MB) once, on a background thread, the first
time the embedding pass runs; after that the feature is fully offline and never blocks startup or a
refresh.

What leaves your machine: requests to the sources you subscribe to (feeds and, with a token,
Raindrop); the one-time download of the embedding model; article text sent to OpenRouter for scoring
and summaries (when a key is set); the URL of a page that every local fetch failed on, sent to
jina.ai (when the reader tier is on); and whatever you or Spyglass's jobs send in your own Claude
sessions.

Article enrichment -- relevance scoring against your interests plus a generated summary, tags, and
category -- runs through OpenRouter using the configured model. Set `OPENROUTER_API_KEY` in `.env`
(or as an environment variable; `SPYGLASS_OPENROUTER_API_KEY` works too). Without a key, collection
and find-similar still work, but cards are not scored or summarized.

## Development

```
uv sync                  # create/refresh .venv from the lockfile
uv run pytest            # Python test suite (80 percent minimum coverage)
uv run ruff check src tests
```

Frontend: `cd frontend && npm install`, then `npx vitest run` for tests and `npm run build` for the
production bundle. Plugin: `cd plugin && npm install`, then `npx vitest run` and `npm run build`.

`scripts/pre_push_guard.py` is an optional git pre-push hook that refuses to push commits whose
messages, file names or added lines hold a private tracker's record number, a personal home-folder
path, an email address other than a no-reply one, or any term you list locally. See the comment at
the top of the script for how to install it.

## Releasing the plugin (for BRAT)

BRAT installs from GitHub releases. The canonical `manifest.json` and `versions.json` live at the
repo root; the release tag must equal the manifest `version` exactly (no `v` prefix).

To cut a release:

1. Bump `version` in root `manifest.json` and add the matching entry to root `versions.json`.
2. Commit, then push a matching tag: `git tag 0.13.0 && git push origin 0.13.0`.
3. The `.github/workflows/release.yml` workflow builds the plugin and publishes a release with
   `manifest.json` + `main.js` attached. BRAT picks it up automatically.

## Licence

Spyglass is free software, licensed under the GNU Affero General Public License, version 3 or (at
your option) any later version: see [LICENSE](LICENSE). The licence follows from a dependency:
**PyMuPDF**, the PDF text extractor in the fetch ladder, is available under the AGPL-3.0 or a
commercial licence from Artifex, so Spyglass uses the AGPL. In short, you may use, change and share
Spyglass; if you share a changed copy, or run a changed copy as a service that other people use over
a network, you must offer them the changed source under the same licence.

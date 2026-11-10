---
name: spyglass
description: Use when the user says "update spyglass", "run my briefing", "curate my feeds", "categorize my spyglass items", "recategorize the list", "filter my spyglass", "run the relevance pass", "hide off-topic items", "spyglass deep dive", or "work on my spyglass selection". Drives the local Spyglass research-dashboard service through its MCP tools to categorize, filter by relevance, curate, and deep-dive collected items, saving briefings into the Obsidian vault.
---

# Spyglass Research Skill

Spyglass is a local research dashboard. A Python service collects RSS and Raindrop items; this
skill is how a Claude session curates them and runs deep dives. All interaction goes through the
`spyglass` MCP server (HTTP, default `http://127.0.0.1:7777/mcp/`).

## Preconditions

1. The `spyglass` MCP tools (get_pending_items, organize, save_cards, fetch_document, save_briefing,
   ...) being available IS the health check -- if they are listed, the service is up. Do NOT curl
   or otherwise make raw HTTP requests to the service (the user's environment may block them and it
   is unnecessary): always go through the MCP tools.
2. If the spyglass MCP tools are NOT available, the service is not running or the MCP server is not
   connected. Tell the user to open Spyglass in Obsidian (the plugin starts the service) and to
   approve the `spyglass` MCP server if Claude Code prompts for it (it is registered by the vault's
   `.mcp.json`, which the service keeps up to date). Do not guess at data.
3. **Sessions opened from the dashboard** open in the Claude desktop app with the request typed in.
   When the request ends with `Cards: #12 "Title", ...`, those are the cards to work on:
   they were selected when the user pressed the button, so prefer them over `get_selection`.
4. **A hand-off.** When the request asks you to call `get_handoff` with an id, do that FIRST and
   treat the returned text as the user's request (the dashboard's prompt was too long for a link).

## Model economy -- applies to categorize and relevance filter

The categorize and relevance workflows are bulk, mechanical judging designed for a cheap model.
A session opened from the dashboard runs on the model chosen in the Claude desktop app, which may be
a stronger (expensive) model. In that case the strong model ORCHESTRATES, it does not judge:

- If your session model is Haiku (or the user asked for inline judging), judge inline as written.
- Otherwise, dispatch the per-item judging to Haiku subagents: send batches of 30-50 items
  (id, title, summary, tags + the profile/preferences text and the existing category names) to a
  subagent (Task tool, model haiku) that returns ONLY a JSON list -- `[{card_id, category}]` for
  categorize, `[{card_id, relevance, reason}]` for the relevance pass. You apply the results via
  the `categorize` / `set_relevance` MCP tools and keep your own turns to orchestration + the
  final report. Stage-2 full-text refinement also goes to Haiku subagents, one batch per subagent.

## Workflow: categorize / review ("categorize my spyglass items", "review categories", "recategorize the list")

Categories are assigned in the background. This workflow handles the cards the
assignment left without one: the "doesn't fit" tail. Lightweight -- use Haiku for any bulk judging;
you orchestrate.

1. Call `get_categories` (the user's managed set) and `get_review_queue`. The queue is a list of
   `{card_id, item_id, title}`: cards with no category yet. It carries no recommendations; you judge
   each title against the managed set (read `get_fulltext` when the title is not enough).

2. For each card in `queue`, propose the best-fit existing category. Apply the user's choice (or
   your proposal if the user waves it through) via `categorize([{card_id, category}])`. If nothing
   fits, do NOT invent a new category: leave it uncategorized and list it as a candidate for a new
   category in your summary (the user creates categories in Settings or with Recategorize).

3. If the user wants to sanity-check categories that are already set, show a few and call
   `confirm_categories([card_id, ...])` for the ones they approve; change the others via
   `categorize`.

4. Report: how many cards were placed, how many confirmed, and the new-category candidates.

`categorize` skips cards the user recategorized by hand -- never re-clobber the user's call.

## Workflow: relevance filter ("filter my spyglass", "run the relevance pass", "hide off-topic items")

Score each item against the user's profile so the dashboard hides what is out of scope. Transparent
and reversible -- nothing is deleted, and the user can change any score. Use Haiku (Sonnet if asked).

1. Call `get_interest_profile` AND `get_preferences`: the profile is what the user wants; the
   preferences note is what they have taught the system over time -- it now also reflects
   the user's thumbs-up/down feedback, folded in by the `spyglass-preferences` skill. Weigh both.
2. Call `get_pending_items(limit=100)` -- each item carries a `card_id`.
3. STAGE 1 (cheap): judge every item on title + summary + tags as high / medium / low / out:
   - high / medium: clearly on-profile and substantive.
   - low: tangential or introductory.
   - out: off-profile (matches a mute / not-interested signal).
4. STAGE 2 (deep, keepers only): for items judged high or medium, call `store_fulltext(card_id)`
   then `get_fulltext(card_id)` and refine the judgment on the real text.
5. Call `set_relevance` with `[{card_id, relevance, reason}]` for every item -- a one-line reason
   each. Cards the user overrode are skipped automatically.
6. Report: how many high / medium / low / out, and the dominant categories among the keepers.

## Workflow: daily curation ("update spyglass")

Collection (fetching new items) is the dashboard's job -- it refreshes on open and via its Refresh
button. This skill works on whatever `get_pending_items` returns; if the user wants fresher items,
ask them to click Refresh in the dashboard first.

1. Call `get_interest_profile` and read it carefully -- it defines what matters.
2. Call `get_pending_items` (optionally just one group the user named).
   For each item, judge against the profile:
   - Substantive match: write ONE short paragraph ("why this matters to you"), pick 1-3 short
     topic tags, and a single `category` (a broad bucket like "Healthcare AI", "Infrastructure").
   - No match or noise: drop it (simply do not include it).
3. Call `save_cards` with the kept items (item_id, summary, tags, category). Report to the user:
   how many pending, kept, dropped, and the dominant categories.

## Linked session (the first message asks you to call link_session)

Spyglass opened this session as its linked Claude session. Call `link_session` with the
code in the message FIRST, then follow the instructions it returns: they replace this skill's
session menu for this session. Item codes such as `#1042` resolve with `get_item`; "this one" and
"these" come from `get_selection`. If a tool says the session is no longer linked, stop and tell
the user to use the newest linked session.

## Workflow: session menu (session opened from the dashboard, no named action)

The dashboard has ONE Claude button; this session builds the menu itself from what is actually
true right now -- so the option list lives HERE, not in the launcher prompt. Your FIRST
action MUST be to gather live context, then present the menu via AskUserQuestion. Do NOT start a
relevance pass, categorize, brief work, or any other workflow until the user picks an option, and
present the options through AskUserQuestion, never as plain text.

**Step 1 -- gather context in parallel (one batch):**
- `get_selection` -- the dashboard's current multi-select (may be empty).
- `review_count` -- how many items await category review.
- `get_brief` -- the latest Daily Brief (returns `{error}` when none exists yet).
- Note whether the **`notebooklm` MCP tools are listed** in this session (e.g.
  `mcp__notebooklm__notebook_query`). Their presence is the availability check -- do not call them
  to test; just observe whether they exist.

**Step 2 -- present ONLY the options that apply.** Build the AskUserQuestion menu from the context:

- **Review category queue** -- include ONLY when `review_count.needs_review > 0`; surface FIRST as
  "N items need category review -- review now?" (N = the count). Runs the categorize / review workflow.
- **Work with today's brief** -- include ONLY when `get_brief` returned a brief (not `{error}`):
  discuss it, deep-dive one of its stories, or (if NotebookLM is available) push it to a notebook.
- **Work on the selection** -- include ONLY when the selection is non-empty: Compare / Synthesize
  into one note / Deep dive each, using stored full text (`get_fulltext`) and `get_highlights`.
- **Ask / build a NotebookLM notebook** -- include ONLY when the `notebooklm` tools are present:
  push the selection, today's brief, or a category to a notebook, or ask a notebook for a grounded
  answer. See the NotebookLM workflow below.
- **Relevance pass** ("filter my spyglass") -- the relevance filter workflow above.
- **Categorize / review items** -- the categorize / review workflow above.
- **Train preferences** -- invoke the `spyglass-preferences` skill (focus on the selection if any).
- **Archive the items** -- `archive_items(card_ids)` clears processed items from the default list
  (restorable from the Archive tab). Offer `remove_from_raindrop=true` only if the user wants the
  underlying Raindrop bookmarks removed too (RSS/arXiv items have none and are skipped).
- **Other** -- the user types what they want.

If a context call fails (e.g. `get_brief`/`review_count` errors), just drop that option and carry
on -- degrade, never abort the menu. Run the chosen workflow; the model-economy rules above apply
to the mechanical passes.

## Workflow: deep dive ("spyglass deep dive", "work on my selection")

1. Call `get_selection`. If empty, ask the user what to dig into (or use the card they named).
2. Research properly: read the source URL, search the web for context, compare viewpoints.
   Respect any note or custom prompt the user attached to the card.
3. Write a briefing in markdown: clear title, findings with sources, what it means for the
   user's projects. No frontmatter -- it is added automatically.
4. Call `save_briefing` with the card id, title, and markdown. Tell the user where it landed.

## Workflow: process documents ("download the papers", "read the linked documents")

For bookmarks that point at papers/PDFs, read the actual document, not just the link.

1. Get the cards: `get_selection`, or the card the user named.
2. For each card, call `fetch_document(card_id)`. It downloads the linked document into the vault
   (PDFs extracted to text; arXiv abstract links resolve to the PDF) and returns the text.
3. Read the returned text. Write a briefing capturing the method, key findings, and relevance to
   the user's projects. Call `save_briefing(card_id, title, markdown)`.
4. Report each saved briefing path and the downloaded document path.

## Workflow: NotebookLM grounding (only when the `notebooklm` MCP is available)

Turn what Spyglass curated into a Google NotebookLM notebook and get citation-backed answers from
it. If a NotebookLM grounding skill is installed (one that creates a notebook from chosen sources
and answers from it with citations), **invoke that skill** and feed it Spyglass sources; this
section is only the Spyglass-side glue. Otherwise do the steps below yourself with the `notebooklm`
MCP tools.

**Availability.** The `notebooklm` MCP tools being listed (e.g. `mcp__notebooklm__notebook_create`,
`mcp__notebooklm__source_add`, `mcp__notebooklm__notebook_query`) is the check. If they are absent,
tell the user NotebookLM is not connected (a NotebookLM MCP server must be installed and signed
in) -- do not attempt a call.

**Push Spyglass sources into a notebook:**
1. Resolve the source set from what the user chose:
   - **Selection** -> `get_selection`, then the chosen cards.
   - **Today's brief** -> `get_brief`; its `cards` array already lists `{card_id, title, url}`.
   - **A category** -> `get_pending_items` filtered to that category.
2. For each source, prefer the **article URL** as a NotebookLM source (`source_add` with
   `source_type="url"`) -- NotebookLM crawls it. When a card has no crawlable URL (YouTube,
   paywalled, or a URL add fails), fall back to its stored full text: `get_fulltext(card_id)` and
   add it as a text source (`source_type="text"` with a `title`).
3. Reuse-before-create and name the notebook `Spyglass -- <topic or brief date>`; if the grounding
   skill keeps a per-project notebook registry, record it there. Report added vs failed counts.
   Spyglass article content is public web material, so no privacy gate is needed here.

**Grounded Q&A:** pick the notebook, `notebook_query`, and return the citation-backed answer naming
the notebook and its sources. If the notebook does not cover the question, say so -- do not fill the
gap from the open web.

## YouTube items

A YouTube card's "full text" is the caption transcript. The service fetches captions itself
(store_fulltext with just the card_id), but when the yt-transcribe skill is available,
PREFER it for quality: run `yt-transcribe video "<url>" --json --no-save`, then
`store_fulltext(card_id, markdown=<the "text" field of its result>)` to store the result directly.

## Rules

- Never invent items: only curate what `get_pending_items` returned.
- Tool docstrings are the contract; when in doubt, re-read them.
- Quota courtesy: curation is a filtering task -- be concise, no purple prose.
- After processing items (briefing, synthesis), offer to `archive_items` them so they leave the
  default list -- archiving is soft (state DISMISSED, restorable), never a delete.

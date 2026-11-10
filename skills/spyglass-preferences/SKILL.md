---
name: spyglass-preferences
description: Use when the user says "train my spyglass preferences", "learn my spyglass preferences", "update my spyglass preferences", or clicks Train preferences in the Spyglass dashboard. Reviews the relevance/category changes the user made by hand and consolidates them into the learned preferences note, asking 1-2 quick questions first.
---

# Spyglass Preference-Training Skill

A dedicated, standalone skill (separate from the `spyglass` skill) that turns the user's
manual relevance/category overrides AND their thumbs-up/down feedback into durable preferences
in the learned-preferences note (its path comes from `get_preferences`; it defaults to a fixed file
next to the database when no vault note is configured). It runs in a vault-rooted Claude
Code session and goes through the `spyglass` MCP server. Keep it short -- Haiku is recommended.

## Why this exists

The relevance pass proposes scores; the user sometimes changes them, and the user also thumbs items
up or down. Both are the SIGNAL of what they actually care about. This skill consolidates the
signal into `preferences.md`, which the relevance pass reads alongside `interests.md`. Reverts are NOT
signals: the override state self-clears when the user toggles a value back to the AI's, so only genuine
net changes appear in `get_overrides`. Thumbs are presence-based (no AI baseline): a cleared thumb simply
drops out of `get_feedback`. A thumbs-up means "more like this"; a thumbs-down means "less like this" --
infer from the item whether the gripe was the topic or the article's quality.

Model economy: this is a short interactive consolidation -- Haiku is enough, and
the dashboard's Train preferences button already spawns the session with `--model haiku`. Keep it
brief either way: read the signals, ask 1-2 questions one at a time, write the note, stop.

## Preconditions

The `spyglass` MCP tools (get_preferences, get_overrides, get_feedback, ...) being available IS the health check.
If they are not listed, tell the user to open Spyglass in Obsidian and approve the `spyglass` MCP
server. Do not guess at data.

## Workflow ("train my spyglass preferences")

1. Call `get_preferences`. It returns `{path, preferences}` -- the current learned note and where it
   lives. If `path` is null, tell the user to set a preferences note path in Settings and stop.
2. Call `get_overrides` AND `get_feedback`.
   - `get_overrides`: cards the user changed -- `card_id`, `title`, `relevance` vs `relevance_ai`,
     `category` vs `category_ai`.
   - `get_feedback`: cards the user thumbed -- `card_id`, `title`, `feedback` ('up'/'down'),
     `relevance`, `category`. Presence-based; cleared thumbs do not appear.
   If BOTH are empty, tell the user there is nothing new to learn and stop.
3. Look for PATTERNS across both signals, not one-offs:
   - Topics repeatedly downgraded to low/out, or thumbed DOWN -> candidate "mute / deprioritize".
   - Topics repeatedly upgraded to high, or thumbed UP -> candidate "prioritize".
   - Recategorizations that reveal a clearer bucket the user prefers.
   - A thumbs-down on an on-topic item is a QUALITY signal (e.g. a source/format to avoid), not a
     topic signal -- infer which from the item and phrase the bullet accordingly.
4. Ask the user AT MOST 1-2 questions, ONE AT A TIME, only when a pattern is ambiguous -- e.g.
   "You moved three crypto items to 'out'. Mute crypto market commentary entirely, or keep
   substantive crypto-infrastructure papers?" Skip questions when the pattern is obvious.
5. Update the note at `path` (Read it first if it exists, then Write/Edit): add or refine concise
   bullet preferences under clear sections (e.g. "Prioritize", "Deprioritize / mute"). Keep it human
   readable and SHORT -- it is the user's note, not a log. Never delete the user's own edits; merge.
6. Report: what you learned (the bullets you added/changed) and how many overrides informed it.

## Rules

- Only consolidate from `get_overrides` and `get_feedback`; never invent preferences the signal does not support.
- preferences.md is distinct from interests.md: interests.md is hand-authored intent, preferences.md
  is learned. Do not duplicate one into the other.
- Be conservative: one clear bullet beats five speculative ones. The user can always edit the note.

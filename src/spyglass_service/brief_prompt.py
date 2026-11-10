# src/spyglass_service/brief_prompt.py
"""Daily Brief prompt contract: schema, message builder, item blocks.

Kept separate from brief.py so the compose logic stays small and the prompt text is easy
to tune. Stable-prefix-first: the system message (task + interest profile) never changes
within a run, so DeepSeek's implicit prompt caching keeps repeated calls cheap.
"""

# Structured output keeps parsing safe: the model must return exactly
# {lead, sections: [{heading, bullets: [str]}, ...]} with at least one section and at
# least one bullet per section (grouped-bullet contract).
BRIEF_SCHEMA = {
    "name": "daily_brief",
    "schema": {
        "type": "object",
        "properties": {
            "lead": {"type": "string"},
            "sections": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "heading": {"type": "string"},
                        "bullets": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["heading", "bullets"],
                },
            },
        },
        "required": ["lead", "sections"],
    },
}

_SYSTEM = (
    "You write a Daily Brief for a single user: a short lead, then thematic sections whose "
    "bodies are GROUPED BULLETS. Judge emphasis ONLY against the user's interest statement "
    "below; you have no other knowledge of them.\n"
    "Rules:\n"
    "- Citation token: articles are shown to you as [#n] (e.g. [#2]), but you must cite "
    "them in your bullets as the BARE number in brackets: [n]. For example, the article "
    "shown as [#2] is cited in a bullet as [2], not [#2]. Use the EXACT number given; "
    "never invent titles, links, or numbers that were not provided.\n"
    "- \"lead\": a detailed, multi-sentence overview of the day's threads -- expand past a "
    "single line into a fuller picture of what the day covers and why it matters. [n] "
    "tokens are allowed here but not required.\n"
    "- One bullet per story is the core rule: EVERY featured article maps to EXACTLY ONE "
    "bullet, and every bullet is grounded in a specific featured article. The number of "
    "bullets is driven by how many genuinely-distinct stories the featured articles tell, "
    "NOT by a target section count.\n"
    "- GROUP genuinely-related articles (the same story, or articles doing the same kind of "
    "work) into ONE bullet and cite ALL their numbers in that single bullet -- PREFER "
    "combining related work over splitting it. Write separate bullets ONLY for genuinely "
    "different stories. NEVER write two bullets about the same article, and never weld "
    "unrelated work into one bullet.\n"
    "- NEVER invent a bullet or a section that is not grounded in a specific featured "
    "article: no themes, framing, or connective tissue that no article actually supports. "
    "If the articles do not support a section, do not write that section.\n"
    "- A day with a single article is a SINGLE bullet in a single section -- do not pad "
    "one article out into a multi-section brief or restate it across bullets.\n"
    "- \"sections\": thematic sections, each grouping the bullets that belong together. Use "
    "as many as the distinct stories warrant and no more (a quiet day is one section). Each "
    "\"heading\": sentence case, plain text, at most 8 words -- no markdown, no [n].\n"
    "- Every bullet is 400-500 characters of real substance: lead with WHAT the grouped "
    "work is, then land WHY it matters to this user. Do not label the bullet ('This is "
    "about...') and do not prefix it with a '**label:**'-style bold tag.\n"
    "- Coverage: reference every featured article at least once across the bullets -- "
    "nothing gets dropped, nothing is duplicated across bullets; never invent articles.\n"
    "- Voice: plain, direct, human.\n"
    "  Use \"is\"/\"are\" for what something does; never \"serves as\", \"acts as\", or "
    "\"functions as\".\n"
    "  No significance inflation: never call something crucial, pivotal, game-changing, "
    "or revolutionary.\n"
    "  No -ing fake-depth openers: never start a bullet with Highlighting, Underscoring, "
    "or Showcasing.\n"
    "  No rule-of-three triads (lists of exactly three parallel items for rhythm).\n"
    "  No em dashes or en dashes (— or –) anywhere -- use a comma, period, or "
    "parentheses instead.\n"
    "  Vary sentence length. No filler, and no upbeat wrap-up conclusion sentence at the "
    "end of a bullet or section.\n"
    "  Do NOT use: underscore, delve, moreover, notably, furthermore, leverage, \"in the "
    "realm of\", \"gains momentum\", \"it's worth noting\", \"plays a crucial role\", or "
    "stacked em-dashes.\n"
    "Return strict JSON matching the schema.\n\n"
    "USER INTEREST STATEMENT:\n{interest}"
)


def item_block(n: int, title: str, summary: str, category: str | None, tags: list[str]) -> str:
    """Render one featured item as the block the narrative prompt consumes.

    Args:
        n: 1-based reference number (the [#n] token the model must use).
        title: Article title.
        summary: The card's LLM summary (from the enrichment pass).
        category: Assigned topic category, or None.
        tags: Topical tags (possibly empty).

    Returns:
        A compact multi-line block: '[#n] title — summary' plus a metadata line.
    """
    lines = [f"[#{n}] {title} — {summary}"]
    meta: list[str] = []
    if category:
        meta.append(f"category: {category}")
    if tags:
        meta.append(f"tags: {', '.join(tags)}")
    if meta:
        lines.append("  (" + "; ".join(meta) + ")")
    return "\n".join(lines)


def build_brief_messages(interest: str, blocks: list[str]) -> list[dict]:
    """Build the chat messages: system (task + interest) first, item blocks in the user turn.

    Args:
        interest: The user's interest statement (stable, cache-friendly prefix).
        blocks: Pre-rendered item blocks from item_block, in reference order.

    Returns:
        A two-element [system, user] messages list for chat_json.
    """
    user = "FEATURED ARTICLES:\n\n" + "\n\n".join(blocks)
    return [
        {"role": "system", "content": _SYSTEM.format(interest=interest or "(none provided)")},
        {"role": "user", "content": user},
    ]

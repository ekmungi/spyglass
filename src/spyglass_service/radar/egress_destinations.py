"""Every outside service Spyglass contacts, what each one receives, and whether it is in use.

This is the documented destinations table. `radar/egress.py` re-exports it, the privacy page
reads it through `destinations_for`, and a regression test fails when code names a host that is
not listed here (or in `LINK_ONLY_HOSTS`, for hosts that only appear in links the reader opens).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

# Hosts that appear in the code only inside links the reader may open in their own browser, or
# only to recognise an address; the service itself never sends a request because of them.
LINK_ONLY_HOSTS: frozenset[str] = frozenset({
    "mail.google.com",  # "open this newsletter in Gmail" links
    "statnews.com",  # recognising a subscriber-only article on a page already fetched
    # The official FDA record page each FDA decision links to. The service reads FDA data from
    # api.fda.gov only; the record page is opened by the reader, or fetched like any other page.
    "www.accessdata.fda.gov",
})


@dataclass(frozen=True)
class Destination:
    """One outside service: who it is, what it is for, and what it is sent.

    hosts: the fixed host names; empty when the destination is "any public website".
    secret: the secret setting sent to it, or None.
    model_influence: whether, and how, an AI model's output can change what is sent.
    enabled: settings -> whether this destination is in use with the current settings.
    """

    key: str
    name: str
    hosts: tuple[str, ...]
    purpose: str
    what_is_sent: str
    secret: str | None
    model_influence: str
    enabled: Callable[[object], bool]


def _on(_settings: object) -> bool:
    """Always in use."""
    return True


def _set(name: str) -> Callable[[object], bool]:
    """In use when the setting `name` is set (truthy)."""
    return lambda s: bool(getattr(s, name, None))


_PAGE = ("The page address, a fixed generic browser identification and standard request headers. "
         "Never cookies, a login, a form or any detail about you.")

DESTINATIONS: tuple[Destination, ...] = (
    Destination("pages", "Web pages and PDFs of items", (),
                "Read the article you open, and the text of items being judged.", _PAGE, None,
                "No: addresses come from your feeds, searches and the links you send in.", _on),
    Destination("feeds", "Feeds you follow", (), "Collect new items from your feeds.", _PAGE,
                None, "No: feeds are the ones you added or kept.", _on),
    Destination("browser", "Headless browser on this computer", (),
                "A last resort for pages that refuse a plain request.", _PAGE + " Each page "
                "opens in a fresh, empty browser profile with downloads and permissions denied.",
                None, "No.", _set("browser_enabled")),
    Destination("bot_checks", "Automated browser checks (for example Cloudflare)",
                ("challenges.cloudflare.com",),
                "Let the built-in browser complete a site's automated check, so the article can "
                "be read. On by default; with it off such pages can be brought in from your own "
                "browser.",
                "Technical details of the built-in browser that the check asks for, sent only to "
                "the checking service's own endpoints. Never a login or anything about you.",
                None, "No.", _set("privacy_allow_bot_checks")),
    Destination("images_service", "Article images (fetched by Spyglass)", (),
                "Show the images inside articles without your browser contacting their sites.",
                _PAGE, None, "No.", _set("privacy_proxy_images")),
    Destination("images_browser", "Article images (fetched by your browser)", (),
                "Show the images inside articles when image proxying is switched off.",
                "Your browser's request to each image's site, as any web page would make it.",
                None, "No.", lambda s: not getattr(s, "privacy_proxy_images", True)),
    Destination("jina", "Outside page renderer (Jina Reader)", ("r.jina.ai",),
                "Render pages that refuse every local method.",
                "The address of the page being read (and its key, when one is set). The service "
                "learns which pages you read.", "jina_api_key", "No.", _set("jina_enabled")),
    Destination("google_news", "Google News search", ("news.google.com",),
                "News searches on your topics (every cycle), watch list and followed subjects.",
                "Search text from your topics, your watch list and subjects you follow; to find "
                "a publisher's address, Google's own article identifiers are sent back to Google.",
                None, "Yes, bounded: suggested search text is checked (at most 200 characters, "
                "one line, no web addresses) and sent only as the search text.", _on),
    Destination("hackernews", "Hacker News search", ("hn.algolia.com", "news.ycombinator.com"),
                "Popular AI stories.", "A fixed search phrase and a date filter.", None, "No.", _on),
    Destination("fda", "FDA device decisions (openFDA)", ("api.fda.gov",),
                "New FDA clearances, De Novo grants, approvals and recalls for the companies on "
                "your watch list.",
                "Each watched company's name, and the product codes and keywords you list, as "
                "search text with a date range. No key, no account, nothing about you.", None,
                "No: the search text comes from your watch list and your own lists; the model "
                "is not involved.", lambda s: bool(getattr(s, "radar_fda_enabled", True))),
    Destination("hf_papers", "Hugging Face daily papers", ("huggingface.co",),
                "The day's most discussed papers.", "A request for the list; nothing about you.",
                None, "No.", _on),
    Destination("arxiv", "arXiv", ("export.arxiv.org", "arxiv.org"),
                "Paper search and paper pages.", "The topic you type into Find papers.", None,
                "No: the search is built from your topic; the model only ranks the results.", _on),
    Destination("github", "GitHub", ("api.github.com", "github.com", "raw.githubusercontent.com"),
                "Read a repository's front page when an item links to one.",
                "The repository name; no GitHub account or token.", None, "No.", _on),
    Destination("youtube", "YouTube", ("www.youtube.com", "www.youtube-nocookie.com",
                                       "i.ytimg.com"),
                "Video transcripts, and the player when you open a video.",
                "The video address; the privacy-enhanced player is used in the reader.", None,
                "No.", _on),
    Destination("openrouter", "OpenRouter (AI models)", ("openrouter.ai",),
                "Judge items for relevance, write summaries and answer assistant questions.",
                "Your profile (statement, sections, topics, avoid list and example titles), item "
                "titles, snippets and article text, and your assistant questions. Known secrets, "
                "your e-mail address and local file paths are removed first.",
                "openrouter_api_key", "Not applicable: this is the model.",
                _set("openrouter_api_key")),
    Destination("claude_code", "Claude Code on this computer (sends to Anthropic)", (),
                "Judging or assistant answers through your Claude subscription.",
                "The same material as for OpenRouter; the program runs with every tool off.",
                None, "Not applicable: this is the model.",
                lambda s: getattr(s, "radar_llm_provider", "") == "claude_code"
                or bool(getattr(s, "assist_claude_code_enabled", False))),
    Destination("anthropic", "Anthropic API (assistant)", ("api.anthropic.com",),
                "Assistant answers with your own API key.",
                "The item you ask about, your profile statement and topics, and the conversation.",
                "anthropic_api_key", "Not applicable: this is the model.",
                _set("anthropic_api_key")),
    Destination("openai", "OpenAI API (assistant)", ("api.openai.com",),
                "Assistant answers with your own API key.",
                "The item you ask about, your profile statement and topics, and the conversation.",
                "openai_api_key", "Not applicable: this is the model.", _set("openai_api_key")),
    Destination("gemini", "Google Gemini API (assistant)", ("generativelanguage.googleapis.com",),
                "Assistant answers with your own API key.",
                "The item you ask about, your profile statement and topics, and the conversation.",
                "gemini_api_key", "Not applicable: this is the model.", _set("gemini_api_key")),
    Destination("local_models", "AI servers you add (this computer or your own server)",
                ("127.0.0.1",), "Assistant answers from a server you configured.",
                "The item you ask about, your profile statement and topics, and the conversation; "
                "a key you stored for that server goes only to that server.", None,
                "Not applicable: this is the model.", lambda _s: False),
    Destination("slack", "Slack", ("slack.com", "files.slack.com"),
                "Read links, pictures and files you post in your capture channel.",
                "Your bot token and the channel id (and, for the live connection, your app token, "
                "which opens a connection to a slack.com address Slack provides). The bot token "
                "also goes to files.slack.com, and only there, to download a file you posted "
                "(PDF, picture, text; at most 20 MB); messages are only read, never posted.",
                "slack_bot_token", "No.",
                lambda s: bool(getattr(s, "slack_bot_token", None)
                               and getattr(s, "slack_capture_channel", None))),
    Destination("gmail", "Gmail (IMAP)", ("imap.gmail.com",),
                "Read newsletters and links you mail to yourself.",
                "Your address and app password; mail is opened read-only and never sent.",
                "gmail_app_password", "No.",
                lambda s: bool(getattr(s, "gmail_address", None)
                               and getattr(s, "gmail_app_password", None))),
    Destination("raindrop", "Raindrop.io", ("api.raindrop.io",), "Read your bookmarks.",
                "Your Raindrop token. In the older card view, deleting a Raindrop item moves it "
                "to a 'Processed' collection in your own account.", "raindrop_token", "No.",
                _set("raindrop_token")),
    Destination("embedding_model", "Hugging Face (one-time model download)", ("huggingface.co",),
                "Download the small local model that finds related items.",
                "A request for the model files; nothing about you.", None, "No.", _on),
)


def documented_hosts() -> frozenset[str]:
    """Every fixed host named in the destinations table."""
    return frozenset(h for d in DESTINATIONS for h in d.hosts)


def destinations_for(settings: object, overrides: Mapping[str, bool] | None = None) -> list[dict]:
    """The destinations table as plain data, with `enabled` evaluated for `settings`.

    overrides: key -> enabled, for destinations whose state is known only elsewhere (for
    example assistant servers configured in the database).
    """
    overrides = overrides or {}
    rows = []
    for d in DESTINATIONS:
        enabled = overrides[d.key] if d.key in overrides else bool(d.enabled(settings))
        rows.append({
            "key": d.key, "name": d.name,
            "host": ", ".join(d.hosts) if d.hosts else "any public website",
            "purpose": d.purpose, "what_is_sent": d.what_is_sent,
            "carries_secret": d.secret is not None, "model_influence": d.model_influence,
            "enabled": enabled,
        })
    return rows

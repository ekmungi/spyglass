"""Recognise pages that are not articles: error pages, bot walls, cookie walls, redirect stubs.

A site that refuses automated reading usually still answers with HTTP 200 and a short page such
as "Just a moment..." or "Please enable JavaScript". Stored as a readable document, that page
would be summarised as if it were the story. The test is deliberately narrow: a page counts
only when it is short AND names a known block phrase (or carries an obvious block title), so a
real short post is never discarded.
"""

import re
from urllib.parse import urlsplit

# The reason stored with a document that was refused (shown to the reader as is).
BLOCKED_REASON = "The site refused automated reading."
# A page with at least this many words is an article, whatever phrases it mentions.
_MAX_BLOCK_WORDS = 120
# A block title on a page with more words than this is a coincidence (a real article about locks).
_MAX_TITLE_WORDS = 300

# Titles block pages carry; matched against the whole title, so a longer headline never matches.
_BLOCK_TITLE = re.compile(
    r"^\s*(?:(?:error\s+)?4(?:03|29)\b.{0,40}|access denied.{0,30}|forbidden|just a moment\W*"
    r"|attention required.{0,40}|verify you are human.{0,30}|are you a (?:robot|human).{0,20}"
    r"|please enable javascript.{0,40}|pardon our interruption.{0,20}|security check.{0,20}"
    r"|one more step.{0,20}|checking your browser.{0,40}|request blocked.{0,20}"
    r"|you have been blocked.{0,20}|redirecting\W*)\s*$",
    re.IGNORECASE,
)
# Phrases that appear in the body of a block page.
_BLOCK_PHRASES = (
    "enable javascript", "javascript is disabled", "javascript is required",
    "verify you are human", "verify that you are human", "verify you are not a robot",
    "you have been blocked", "access denied", "403 forbidden", "request blocked",
    "checking your browser", "review the security of your connection", "unusual traffic",
    "are you a robot", "are you a human", "complete the security check",
    "enable cookies", "cookies must be enabled", "accept cookies to continue",
    "click here if you are not redirected", "you are being redirected",
    "if you are not redirected", "performing security verification",
    "protect against malicious bots", "protect itself from online attacks", "triggered the security solution", "verifies you are not a bot", "checking if the site connection is secure",
)


def looks_blocked(text: str, title: str = "") -> bool:
    """True when a fetched page is a block page rather than the article that was asked for.

    `text` is the page's plain text and `title` its title. A page is blocked when it has fewer
    than about 120 words and contains a block phrase, or when its title is an obvious block
    title and it has no more than a few hundred words.
    """
    words = len(text.split())
    if words == 0:
        return False
    if title and _BLOCK_TITLE.match(title) and words <= _MAX_TITLE_WORDS:
        return True
    if words >= _MAX_BLOCK_WORDS:
        return False
    lowered = text.lower()
    return any(phrase in lowered for phrase in _BLOCK_PHRASES)


# --- stub pages: trackers, redirect stubs, navigation-only pages ---------------------------------

# The reason stored with a document that holds no article at all (shown to the reader as is).
STUB_REASON = "No readable article was found at this address."
# A page that ended on another website than the one asked for is a stub below this many words.
_OFF_SITE_MAX_WORDS = 150
# A page below this many words must contain a real paragraph, or it is a menu or a share widget.
_SHORT_PAGE_WORDS = 60
# A paragraph of at least this many words counts as real prose.
_REAL_PARAGRAPH_WORDS = 25
# A paragraph this long proves an article even after a redirect to another website.
_PROSE_PARAGRAPH_WORDS = 60
# Second-level labels under which a country domain is registered ("example.co.uk").
_SECOND_LEVEL = {"co", "com", "org", "net", "gov", "ac", "edu", "ne", "or", "go"}
_PIXEL = re.compile(
    r"\b1\s?x\s?1\b.{0,40}\b(?:image|pixel|gif)\b|tracking pixel|track(?:er)? (?:probe|pixel)|tacker probe",
    re.IGNORECASE | re.DOTALL,
)


def registrable_domain(url: str) -> str:
    """The registrable domain of `url` ("news.bbc.co.uk" gives "bbc.co.uk"); "" when it has no host."""
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    labels = [label for label in host.split(".") if label]
    if len(labels) < 2:
        return ""
    keep = 3 if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in _SECOND_LEVEL else 2
    return ".".join(labels[-keep:])


def _longest_paragraph(text: str) -> int:
    """Word count of the longest blank-line separated paragraph of `text`."""
    return max((len(block.split()) for block in re.split(r"\n\s*\n", text)), default=0)


def is_stub_page(text: str, item_url: str, final_url: str) -> bool:
    """True when the fetched page holds no article: a tracker, a redirect stub or only page furniture.

    `text` is the page's plain text, `item_url` the address the item points to and `final_url` the
    address the fetch ended on. Three tests, each deliberately narrow so that a short post with
    one real paragraph still passes: the page ended on another website and has under 150 words
    (without a long paragraph); it is mostly the description of a one-pixel image; or it has
    under 60 words and no paragraph of 25 words.
    """
    words = len(text.split())
    longest = _longest_paragraph(text)
    other_site = bool(final_url) and registrable_domain(final_url) != registrable_domain(item_url)
    if other_site and words < _OFF_SITE_MAX_WORDS and longest < _PROSE_PARAGRAPH_WORDS:
        return True
    if words < _SHORT_PAGE_WORDS and _PIXEL.search(text):
        return True
    return words < _SHORT_PAGE_WORDS and longest < _REAL_PARAGRAPH_WORDS

"""Automated browser checks ("Just a moment...") in the headless browser rung.

Some sites answer an automated browser with an interstitial page that runs a check and then
navigates to the real page. Completing such a check usually needs the browser to POST technical
data about itself to the checking service, which the browser's read-only rule forbids. So:

- With the switch off (`privacy_allow_bot_checks` false) the browser sends reads only. It waits
  up to `WAIT_OFF_SECONDS` for an interstitial to clear on its own and otherwise fails with
  `BOT_CHECK_REASON`.
- With the switch on, which is the default, the browser may also send non-read requests to the
  checking service's own challenge endpoints, and nowhere else: a path under
  `/cdn-cgi/challenge-platform/` on the page's own registrable domain, or the host
  `challenges.cloudflare.com`. It waits up to `WAIT_ON_SECONDS`. Private addresses stay refused
  either way.

Which domain counts as "the page's own" is decided only by main-frame navigations: a frame the
page embeds (which the page controls) never adds a domain, and a write is accepted only from a
frame on one of those domains or from the checking service's own host.

The registrable domain is worked out without a public-suffix list (none is a declared
dependency): the last two labels, or the last three when the name ends in a common two-part
country suffix such as `co.uk` or a well-known shared hosting domain such as `github.io`. The
limit: a suffix that is in neither list (for example `.nom.fr`) is treated as an ordinary
two-label domain, so every site under it counts as one site. That widens the allowance for
such suffixes by the width of the suffix, never beyond the challenge path.
"""

import time
from collections.abc import Callable
from urllib.parse import urlsplit

# The failure reason when a check does not clear.
BOT_CHECK_REASON = "The site asked for an automated browser check."
# Seconds to wait for an interstitial to clear: on its own (switch off) or by completing it (on).
WAIT_OFF_SECONDS = 8.0
WAIT_ON_SECONDS = 20.0
# Milliseconds between two looks at the page while waiting.
POLL_MS = 500

# The checking service's own challenge path and host.
CHALLENGE_PATH = "/cdn-cgi/challenge-platform/"
CHALLENGE_HOST = "challenges.cloudflare.com"

# Phrases that identify an automated-check interstitial (title or body, lower case).
_PHRASES = (
    "just a moment...", "verification successful. waiting for", "performing security verification",
    "checking your browser", "checking if the site connection is secure", "verify you are human",
    "attention required! | cloudflare", "please wait while we verify", "ddos protection by",
    "enable javascript and cookies to continue",
)
# Second-level labels that, under a two-letter country code, form a two-part public suffix.
_SECOND_LEVEL = frozenset({
    "co", "com", "org", "net", "ac", "gov", "edu", "ne", "or", "go", "mil", "gob", "nom",
    "ltd", "plc", "sch", "nhs", "gv", "info", "biz", "web", "id", "ad",
})
# Hosting domains whose subdomains belong to different owners: each subdomain is its own site.
_SHARED_HOSTS = frozenset({
    "github.io", "gitlab.io", "blogspot.com", "wordpress.com", "vercel.app", "netlify.app",
    "pages.dev", "workers.dev", "herokuapp.com", "azurewebsites.net", "web.app", "firebaseapp.com",
    "appspot.com", "substack.com", "medium.com", "tumblr.com", "wixsite.com", "weebly.com",
    "s3.amazonaws.com", "cloudfront.net", "onrender.com", "fly.dev", "glitch.me", "repl.co",
})

# Replaced in tests: the clock the wait is measured by.
_clock = time.monotonic


def wait_seconds(allow_bot_checks: bool) -> float:
    """How long the browser waits for an interstitial to clear under the switch's setting."""
    return WAIT_ON_SECONDS if allow_bot_checks else WAIT_OFF_SECONDS


def registrable_domain(host: str) -> str:
    """The domain a site registered (`news.example.com` -> `example.com`), approximately."""
    labels = [label for label in (host or "").lower().strip(".").split(".") if label]
    if len(labels) <= 2:
        return ".".join(labels)
    if ".".join(labels[-2:]) in _SHARED_HOSTS or ".".join(labels[-3:]) in _SHARED_HOSTS:
        suffix_len = 3 if ".".join(labels[-3:]) in _SHARED_HOSTS else 2
        return ".".join(labels[-(suffix_len + 1):])
    if len(labels[-1]) == 2 and labels[-2] in _SECOND_LEVEL:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _frame_of(request) -> object | None:
    """The frame that made `request`, or None when the browser cannot name it."""
    try:
        return request.frame
    except Exception:  # noqa: BLE001 -- the browser raises its own error for a frame-less request
        return None


def is_main_frame_navigation(request) -> bool:
    """True when `request` loads a page into the top-level frame (not an embedded one).

    A navigation request whose frame is unknown counts as NOT main-frame: the page cannot be
    allowed to widen the allowance on a request the browser cannot attribute.
    """
    is_nav = getattr(request, "is_navigation_request", None)
    if not callable(is_nav) or not is_nav():
        return False
    frame = _frame_of(request)
    return frame is not None and getattr(frame, "parent_frame", object()) is None


def frame_may_post(request, page_domains: set[str]) -> bool:
    """True when the frame that made `request` is on a page domain or is the checking service's own.

    A write from any other frame (an embedded foreign frame, a blank or unreadable one) is refused.
    """
    frame = _frame_of(request)
    parts = urlsplit(str(getattr(frame, "url", "") or ""))
    host = (parts.hostname or "").lower()
    if parts.scheme.lower() != "https" or not host:
        return False
    return host == CHALLENGE_HOST or registrable_domain(host) in page_domains


def is_challenge_request(url: str, page_domains: set[str]) -> bool:
    """True when `url` is the checking service's challenge endpoint for one of the page's domains.

    Either the challenge host itself, or a path under `CHALLENGE_PATH` on a host whose
    registrable domain is one the page's main frame has navigated to.
    """
    parts = urlsplit(url or "")
    host = (parts.hostname or "").lower()
    if parts.scheme.lower() != "https" or not host:
        return False
    if host == CHALLENGE_HOST:
        return True
    return parts.path.startswith(CHALLENGE_PATH) and registrable_domain(host) in page_domains


def looks_like_bot_check(title: str, html: str) -> bool:
    """True when a page's title or body carries a known interstitial phrase."""
    text = f"{title or ''}\n{(html or '')[:20000]}".lower()
    return any(phrase in text for phrase in _PHRASES)


def _title(page) -> str:
    """The page title, or empty when the page cannot give one."""
    getter = getattr(page, "title", None)
    return str(getter()) if callable(getter) else ""


def wait_out_bot_check(page, timeout_s: float, *, clock: Callable[[], float] | None = None) -> bool:
    """Wait (up to `timeout_s`) while the page shows an interstitial; True once it is gone.

    The page is looked at every `POLL_MS` milliseconds through the browser's own wait, so the
    page keeps running (and can navigate to the real article) while this waits.
    """
    now = clock or _clock
    deadline = now() + timeout_s
    while looks_like_bot_check(_title(page), page.content()):
        if now() >= deadline:
            return False
        page.wait_for_timeout(POLL_MS)
    return True

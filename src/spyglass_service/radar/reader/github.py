"""GitHub repositories: the README as rendered by GitHub, with relative links made absolute.

Only a repository root URL qualifies (not an issue, a file or a release page). The request is
unauthenticated; when GitHub refuses it (rate limit) the builder returns None and the caller
falls back to the generic article path.
"""

import logging
import re

from bs4 import BeautifulSoup

from spyglass_service.radar.reader.article import count_words
from spyglass_service.radar.reader.http import Fetcher
from spyglass_service.radar.reader.sanitize import clean_html

logger = logging.getLogger(__name__)

# Not repositories: the first path segment is a GitHub feature page.
_RESERVED = (
    "orgs|settings|explore|notifications|marketplace|topics|sponsors|features|about|pricing|login|"
    "collections|trending|search|issues|pulls|apps|enterprise|security|customer-stories|readme"
)
_REPO_URL = re.compile(
    rf"^https?://(?:www\.)?github\.com/(?!(?:{_RESERVED})/)([\w.-]+)/([\w.-]+?)(?:\.git)?/?(?:[?#].*)?$",
    re.IGNORECASE,
)
_API_HEADERS = {
    "Accept": "application/vnd.github.html",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "spyglass-reader",
}


def github_repo(url: str) -> tuple[str, str] | None:
    """(owner, repo) when `url` is a repository root, else None."""
    match = _REPO_URL.match(url.strip())
    return (match.group(1), match.group(2)) if match else None


def _is_relative(value: str) -> bool:
    """True for a path-relative reference (not absolute, protocol-relative or a fragment)."""
    value = value.strip()
    return bool(value) and not value.startswith(("#", "/", "//")) and ":" not in value.split("/")[0]


def _strip_dot(path: str) -> str:
    """Drop a leading "./" from a relative path."""
    return re.sub(r"^\./", "", path.strip())


def _absolutise_readme(fragment: str, owner: str, repo: str) -> str:
    """Point relative images at the raw file host and relative links at the repo file view."""
    raw_base = f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/"
    blob_base = f"https://github.com/{owner}/{repo}/blob/HEAD/"
    soup = BeautifulSoup(fragment, "html.parser")
    for tag in soup.find_all(["img", "source"]):
        src = str(tag.get("src", "")).strip()
        if src and _is_relative(src):
            tag["src"] = raw_base + _strip_dot(src)
        srcset = str(tag.get("srcset", "")).strip()
        if srcset:
            first, *rest = srcset.split()
            if _is_relative(first):
                tag["srcset"] = " ".join([raw_base + _strip_dot(first), *rest])
    for tag in soup.find_all("a"):
        href = str(tag.get("href", "")).strip()
        if _is_relative(href):
            tag["href"] = blob_base + _strip_dot(href)
        elif href.startswith("/") and not href.startswith("//"):
            tag["href"] = "https://github.com" + href
    return str(soup)


def build_github(owner: str, repo: str, *, url: str, fetch: Fetcher) -> dict | None:
    """Reader fields for a repository's README, or None when GitHub could not supply it."""
    page = fetch(f"https://api.github.com/repos/{owner}/{repo}/readme", headers=_API_HEADERS)
    if not page.ok or not page.text.strip():
        logger.info("GitHub README for %s/%s unavailable: %s", owner, repo, page.error)
        return None
    repo_url = f"https://github.com/{owner}/{repo}"
    cleaned = clean_html(_absolutise_readme(page.text, owner, repo), repo_url + "/")
    words = count_words(cleaned)
    if words < 5:
        return None
    return {
        "kind": "article", "html": cleaned, "title": f"{owner}/{repo}", "byline": owner,
        "site": "GitHub", "lead_image": "", "word_count": words, "source_url": url, "alt_url": None,
    }

"""Tests for the GitHub builder: repo URL detection, README fixing and the rate-limit fallback."""

import pytest

from spyglass_service.radar.reader.github import build_github, github_repo
from spyglass_service.radar.reader.http import Page

_README = (
    '<div id="readme" class="md" data-path="README.md"><article class="markdown-body">'
    '<div class="markdown-heading"><h1>Cool Tool</h1><a id="user-content-cool" class="anchor" href="#cool">'
    '<svg viewBox="0 0 1 1"><path d="m"/></svg></a></div>'
    '<p>Cool Tool does many useful things for you. See the <a href="docs/guide.md">guide</a> and the '
    '<a href="/owner/repo/issues">issues</a> or <a href="https://example.com/x">the site</a>.</p>'
    '<p><img src="assets/logo.png" alt="Logo"><img src="https://camo.example/img.png" alt="remote"></p>'
    '<picture><source media="(prefers-color-scheme: dark)" srcset="assets/dark.svg">'
    '<img src="assets/light.svg"></picture>'
    '<pre><code class="language-bash">npm install cool</code></pre></article></div>'
)


@pytest.mark.parametrize("url,expected", [
    ("https://github.com/owner/repo", ("owner", "repo")),
    ("https://github.com/owner/repo/", ("owner", "repo")),
    ("https://www.github.com/owner/repo.git", ("owner", "repo")),
    ("https://github.com/owner/some.repo-name?tab=readme", ("owner", "some.repo-name")),
])
def test_github_repo_detects_repository_roots(url: str, expected: tuple[str, str]) -> None:
    assert github_repo(url) == expected


@pytest.mark.parametrize("url", [
    "https://github.com/owner/repo/issues/3", "https://github.com/owner/repo/blob/main/a.py",
    "https://github.com/orgs/foo/people", "https://github.com/settings/profile",
    "https://github.com/owner", "https://gitlab.com/owner/repo", "https://github.com/",
])
def test_github_repo_rejects_other_urls(url: str) -> None:
    assert github_repo(url) is None


def test_readme_is_rendered_with_relative_urls_fixed() -> None:
    calls: list[tuple[str, dict | None]] = []

    def fetch(url: str, headers=None) -> Page:
        calls.append((url, headers))
        return Page(url=url, ok=True, body=_README.encode(), content_type="application/vnd.github.html")

    result = build_github("owner", "repo", url="https://github.com/owner/repo", fetch=fetch)
    html = result["html"]
    assert calls[0][0] == "https://api.github.com/repos/owner/repo/readme"
    assert calls[0][1]["Accept"] == "application/vnd.github.html"
    assert 'src="https://raw.githubusercontent.com/owner/repo/HEAD/assets/logo.png"' in html
    assert "https://raw.githubusercontent.com/owner/repo/HEAD/assets/dark.svg" in html
    assert 'href="https://github.com/owner/repo/blob/HEAD/docs/guide.md"' in html
    assert 'href="https://github.com/owner/repo/issues"' in html
    assert 'src="https://camo.example/img.png"' in html
    assert "<svg" not in html and "#cool" not in html
    assert "language-bash" in html
    assert result["title"] == "owner/repo" and result["site"] == "GitHub" and result["kind"] == "article"


def test_rate_limit_returns_none_so_the_caller_can_fall_back() -> None:
    def fetch(url: str, headers=None) -> Page:
        return Page(url=url, ok=False, status=403, error="HTTP 403")

    assert build_github("owner", "repo", url="https://github.com/owner/repo", fetch=fetch) is None


def test_an_empty_readme_returns_none() -> None:
    def fetch(url: str, headers=None) -> Page:
        return Page(url=url, ok=True, body=b"<div></div>")

    assert build_github("o", "r", url="u", fetch=fetch) is None


def test_hostile_readme_markup_is_sanitised() -> None:
    hostile = ("<article><p>Safe words here and more words to count for the check</p>"
               "<script>alert(1)</script><img src=x onerror=alert(1)></article>")

    def fetch(url: str, headers=None) -> Page:
        return Page(url=url, ok=True, body=hostile.encode())

    result = build_github("o", "r", url="u", fetch=fetch)
    assert "alert(1)" not in result["html"] and "onerror" not in result["html"]

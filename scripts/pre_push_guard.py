"""Optional git pre-push hook: refuse to push commits that carry private material.

It checks every commit the remote does not have yet: the commit message, the names of the files
it adds, changes or renames (binary files included), and every line it adds. It refuses the push
when it finds
  - a record number from a private tracker (letters, a hyphen and a number, such as a
    decision or issue identifier),
  - an absolute path into a person's home folder (Windows, macOS or Linux), apart from
    placeholder names such as `me` that tests use,
  - an email address other than a no-reply or example address,
  - any term listed in the untracked file `.git/info/pre-push-terms` (one regular expression per
    line, matched without regard to case; `#` starts a comment). Put names that must never be
    published there, such as your own name or private project names.

Install it once per clone: create the file `.git/hooks/pre-push` holding these two lines (Git for
Windows runs hooks through its own sh, so this works there too):

    #!/bin/sh
    exec python scripts/pre_push_guard.py "$@"

If `python` is not on the PATH that git sees, write `uv run --no-project python` in its place.
Use `git push --no-verify` to skip it for one push.
"""
from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import TextIO

ZERO_SHA = "0" * 40
TERMS_FILE = "info/pre-push-terms"
# Third-party package metadata, not text written for this project.
LOCKFILES = frozenset({"uv.lock", "package-lock.json"})

_RECORD = re.compile(
    r"(?<![A-Za-z0-9])(?:DEC|ISS|SPEC|R|F|P|T)-\d{1,4}(?![0-9])"
    r"|(?<![A-Za-z0-9])(?i:spec|dec|iss)_?\d{2,4}(?![0-9])"
    # lower-case hyphenated forms, but not version strings such as a package's spec-1.1.0
    r"|(?<![A-Za-z0-9])(?i:spec|dec|iss)-\d{1,4}(?![0-9]|\.\d)"
)
_PLACEHOLDER = r"(?:me|you|user|username|TestUser|Public|Default|<[^>]+>)"
_HOME_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/]+|/[a-z]/)Users[\\/]+(?!" + _PLACEHOLDER + r"(?:[\\/]|\b))[^\\/\s\"'`]+"
    r"|/(?:home|Users)/(?!" + _PLACEHOLDER + r"(?:/|\b))[A-Za-z0-9._-]+",
)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_EMAIL_ALLOWED = re.compile(
    r"@users\.noreply\.github\.com$|^noreply@anthropic\.com$|^git@github\.com$"
    r"|@example\.(?:com|org|net)$",
    re.IGNORECASE,
)


def load_terms(path: Path) -> list[re.Pattern[str]]:
    """Read the extra private terms, one regular expression per line; none if the file is absent."""
    if not path.is_file():
        return []
    terms = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            terms.append(re.compile(line, re.IGNORECASE))
    return terms


def find_problems(text: str, extra: list[re.Pattern[str]]) -> list[tuple[str, str]]:
    """Return (kind, matched text) for every refused pattern in `text`."""
    found: list[tuple[str, str]] = []
    found += [("record", m.group(0)) for m in _RECORD.finditer(text)]
    found += [("home-path", m.group(0)) for m in _HOME_PATH.finditer(text)]
    found += [
        ("email", m.group(0)) for m in _EMAIL.finditer(text) if not _EMAIL_ALLOWED.search(m.group(0))
    ]
    for term in extra:
        found += [("term", m.group(0)) for m in term.finditer(text)]
    return found


def problems_in_line(line: str, path: str, extra: list[re.Pattern[str]]) -> list[tuple[str, str]]:
    """Like find_problems, but email addresses inside lockfiles are not ours, so they pass."""
    found = find_problems(line, extra)
    if Path(path).name in LOCKFILES:
        found = [item for item in found if item[0] != "email"]
    return found


def _git(*args: str) -> str:
    # quotePath off: git prints non-ASCII file names as they are instead of octal escapes.
    result = subprocess.run(
        ["git", "-c", "core.quotePath=false", *args], capture_output=True, check=True,
    )
    return result.stdout.decode("utf-8", errors="replace")


def commits_to_check(remote: str, updates: Iterable[str]) -> list[str]:
    """List the commits each pushed ref adds that the remote does not already have."""
    commits: list[str] = []
    for update in updates:
        parts = update.split()
        if len(parts) != 4:
            continue
        _local_ref, local_sha, _remote_ref, remote_sha = parts
        if local_sha == ZERO_SHA:
            continue  # a branch deletion pushes no content
        if remote_sha == ZERO_SHA:
            span = [local_sha, "--not", f"--remotes={remote}"]
        else:
            span = [f"{remote_sha}..{local_sha}"]
        for sha in _git("rev-list", *span).split():
            if sha not in commits:
                commits.append(sha)
    return commits


def _against_parent(sha: str, *options: str) -> str:
    """Diff the commit against its first parent (or, for a root commit, against nothing)."""
    parents = _git("rev-list", "--parents", "-n", "1", sha).split()[1:]
    if parents:
        return _git("diff", *options, parents[0], sha)
    return _git("diff-tree", "-r", "--root", *options, sha)


def _touched_paths(sha: str) -> list[str]:
    """Every path the commit adds, changes or renames to, binary files included."""
    names = _against_parent(sha, "--name-only", "--diff-filter=d", "-z")
    return [name for name in names.split("\0") if name]


def _diff_path(header: str) -> str:
    """The new path from a `+++ b/...` line; git quotes names holding special characters."""
    name = header[4:]
    if name.startswith('"') and name.endswith('"'):
        name = name[1:-1]
    return name[2:] if name.startswith("b/") else ""


def _added_lines(sha: str) -> Iterable[tuple[str, int, str]]:
    """Yield (path, line number, text) for every line the commit adds against its first parent."""
    diff = _against_parent(sha, "-p", "-U0", "--no-color", "--no-ext-diff")
    path, lineno = "", 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = _diff_path(line)
        elif line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            lineno = int(match.group(1)) if match else 0
        elif line.startswith("+") and path:
            yield path, lineno, line[1:]
            lineno += 1


def check_commit(sha: str, extra: list[re.Pattern[str]]) -> list[str]:
    """Return one report line per refused match in the commit's message, paths and added lines."""
    short = sha[:10]
    report: list[str] = []
    for kind, token in find_problems(_git("log", "-1", "--format=%B", sha), extra):
        report.append(f"{short} message: {kind} {token!r}")
    for path in _touched_paths(sha):
        for kind, token in find_problems(path, extra):
            report.append(f"{short} path {path}: {kind} {token!r}")
    for path, lineno, text in _added_lines(sha):
        for kind, token in problems_in_line(text, path, extra):
            report.append(f"{short} {path}:{lineno}: {kind} {token!r}")
    return report


def main(argv: list[str], stdin: TextIO, out: TextIO) -> int:
    """Hook entry point: argv is [remote name, remote url]; stdin lists the refs being pushed."""
    remote = argv[0] if argv else "origin"
    extra = load_terms(Path(_git("rev-parse", "--git-path", TERMS_FILE).strip()))
    report: list[str] = []
    for sha in commits_to_check(remote, stdin.read().splitlines()):
        report += check_commit(sha, extra)
    if not report:
        return 0
    out.write("pre-push guard: refusing the push; these commits carry private material:\n")
    out.writelines(f"  {line}\n" for line in report)
    out.write("Fix the commits (or push with --no-verify if you are sure).\n")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], sys.stdin, sys.stderr))

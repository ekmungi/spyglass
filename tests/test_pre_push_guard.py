"""Tests for scripts/pre_push_guard.py, the optional git pre-push hook.

Sample texts that the guard must refuse are assembled at run time, so this file itself never
holds a record number, a home-folder path or an address the guard would refuse.
"""
from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
from pathlib import Path

import pytest

GUARD_PATH = Path(__file__).resolve().parents[1] / "scripts" / "pre_push_guard.py"
ZERO = "0" * 40


def _load_guard():
    spec = importlib.util.spec_from_file_location("pre_push_guard", GUARD_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["pre_push_guard"] = module
    spec.loader.exec_module(module)
    return module


guard = _load_guard()

RECORD = "SP" + "EC-016"
HOME_PATH = "C:" + "\\Users\\" + "alice\\Dev\\project"
POSIX_HOME = "/" + "home/" + "alice/project"
EMAIL = "alice" + "@" + "mail.example-isp.net"


def kinds(text: str, extra=()) -> list[str]:
    return [kind for kind, _token in guard.find_problems(text, list(extra))]


def test_flags_a_record_number():
    assert kinds(f"# Lean payload ({RECORD})") == ["record"]


def test_flags_a_compact_record_number():
    assert kinds("see " + "spec" + "016 for why") == ["record"]


def test_flags_a_lower_case_record_number():
    assert kinds("see " + "dec" + "-033 for why") == ["record"]


def test_leaves_fetch_tiers_plain_words_and_versions_alone():
    text = 'tier="T0"; Phase 2 of the ladder; spec-1.1.0.tgz; F1 score; step 3'
    assert kinds(text) == []


def test_flags_a_windows_home_folder_path():
    assert kinds(f"vault = '{HOME_PATH}'") == ["home-path"]


def test_flags_a_posix_home_folder_path():
    assert kinds(f"root = '{POSIX_HOME}'") == ["home-path"]


def test_allows_placeholder_home_folders():
    text = 'Path("C:/Users/me/My Vault"); "C:\\\\Users\\\\TestUser\\\\AppData"; /home/me/vault'
    assert kinds(text) == []


def test_flags_a_personal_email_address():
    assert kinds(f"contact {EMAIL}") == ["email"]


def test_allows_no_reply_and_example_addresses():
    text = (
        "Co-Authored-By: Claude <noreply@anthropic.com>; "
        "someone@users.noreply.github.com; user@example.com; git@github.com:owner/repo"
    )
    assert kinds(text) == []


def test_extra_terms_match_case_insensitively(tmp_path: Path):
    terms = tmp_path / "terms"
    terms.write_text("# private names\n\nsecretproduct\n", encoding="utf-8")
    extra = guard.load_terms(terms)
    assert kinds("uses the SecretProduct skill", extra) == ["term"]
    assert kinds("uses the public skill", extra) == []


def test_missing_terms_file_means_no_extra_terms(tmp_path: Path):
    assert guard.load_terms(tmp_path / "absent") == []


def test_email_check_skips_lockfiles():
    assert guard.problems_in_line(f'"author": "{EMAIL}"', "uv.lock", []) == []
    assert guard.problems_in_line(f'"author": "{EMAIL}"', "src/a.py", []) == [("email", EMAIL)]


# --- the hook end to end, against a throwaway repository -------------------------------------


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", *args],
        cwd=repo, capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "README.md").write_text("A clean project.\n", encoding="utf-8")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-q", "-m", "Start the project")
    return tmp_path


def _push_line(repo: Path, remote_sha: str = ZERO) -> str:
    head = _git(repo, "rev-parse", "HEAD")
    return f"refs/heads/main {head} refs/heads/main {remote_sha}\n"


def _run_hook(repo: Path, stdin: str, monkeypatch: pytest.MonkeyPatch) -> tuple[int, str]:
    monkeypatch.chdir(repo)
    out = io.StringIO()
    code = guard.main(["origin", "https://example.com/repo.git"], io.StringIO(stdin), out)
    return code, out.getvalue()


def test_hook_passes_a_clean_push(repo: Path, monkeypatch: pytest.MonkeyPatch):
    code, _ = _run_hook(repo, _push_line(repo), monkeypatch)
    assert code == 0


def test_hook_refuses_a_record_number_in_a_commit_message(repo, monkeypatch):
    (repo / "a.txt").write_text("fine\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", f"fix: lean payload ({RECORD})")
    code, report = _run_hook(repo, _push_line(repo), monkeypatch)
    assert code == 1
    assert "message" in report and RECORD in report


def test_hook_refuses_a_home_path_in_an_added_line(repo, monkeypatch):
    first = _git(repo, "rev-parse", "HEAD")
    (repo / "cfg.py").write_text(f"ROOT = r'{HOME_PATH}'\n", encoding="utf-8")
    _git(repo, "add", "cfg.py")
    _git(repo, "commit", "-q", "-m", "Add config")
    code, report = _run_hook(repo, _push_line(repo, remote_sha=first), monkeypatch)
    assert code == 1
    assert "cfg.py:1" in report


def test_hook_checks_only_commits_the_remote_lacks(repo, monkeypatch):
    (repo / "cfg.py").write_text(f"ROOT = r'{HOME_PATH}'\n", encoding="utf-8")
    _git(repo, "add", "cfg.py")
    _git(repo, "commit", "-q", "-m", "Add config")
    bad = _git(repo, "rev-parse", "HEAD")
    (repo / "b.txt").write_text("fine\n", encoding="utf-8")
    _git(repo, "add", "b.txt")
    _git(repo, "commit", "-q", "-m", "Add b")
    code, _ = _run_hook(repo, _push_line(repo, remote_sha=bad), monkeypatch)
    assert code == 0


def test_hook_ignores_a_branch_deletion(repo, monkeypatch):
    code, _ = _run_hook(repo, f"(delete) {ZERO} refs/heads/old {'1' * 40}\n", monkeypatch)
    assert code == 0


def test_hook_refuses_a_record_number_in_a_renamed_file_name(repo, monkeypatch):
    first = _git(repo, "rev-parse", "HEAD")
    _git(repo, "mv", "README.md", f"notes-{RECORD}.md")
    _git(repo, "commit", "-q", "-m", "Rename the readme")
    code, report = _run_hook(repo, _push_line(repo, remote_sha=first), monkeypatch)
    assert code == 1
    assert "path" in report and RECORD in report


def test_hook_refuses_a_record_number_in_a_binary_file_name(repo, monkeypatch):
    first = _git(repo, "rev-parse", "HEAD")
    (repo / f"scan-{RECORD}.bin").write_bytes(b"\x00\x01\x02")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "Add a binary")
    code, report = _run_hook(repo, _push_line(repo, remote_sha=first), monkeypatch)
    assert code == 1
    assert RECORD in report


def test_hook_checks_lines_of_a_file_with_a_non_ascii_name(repo, monkeypatch):
    first = _git(repo, "rev-parse", "HEAD")
    (repo / "café.txt").write_text(f"ROOT = '{HOME_PATH}'\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "Add a note")
    code, report = _run_hook(repo, _push_line(repo, remote_sha=first), monkeypatch)
    assert code == 1
    assert "home-path" in report


def test_hook_reads_extra_terms_from_the_repository_info_folder(repo, monkeypatch):
    info = Path(_git(repo, "rev-parse", "--git-path", "info"))
    info = info if info.is_absolute() else repo / info
    info.mkdir(parents=True, exist_ok=True)
    (info / "pre-push-terms").write_text("secretproduct\n", encoding="utf-8")
    (repo / "c.txt").write_text("Built with SecretProduct.\n", encoding="utf-8")
    _git(repo, "add", "c.txt")
    _git(repo, "commit", "-q", "-m", "Add c")
    code, report = _run_hook(repo, _push_line(repo), monkeypatch)
    assert code == 1
    assert "c.txt:1" in report

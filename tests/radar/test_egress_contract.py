"""A standing gate on how data leaves the machine. It reads the source, so a change that adds a
new way out fails the build until it is routed through the approved pieces:

(a) radar code builds HTTP clients only through the two approved factories:
    `netguard.page_client` / `netguard.guard_client` (page fetching: public addresses, reads only,
    no cookies) and `egress.api_client` (model and service APIs: each secret bound to its host);
(b) every outside host named in the code is in the documented destinations table
    (`radar/egress_destinations.py`) or is a link-only host;
(c) model calls go through the two prompt seams (`radar/llm.py::chat_json_for` and
    `radar/assist/threads.py::run_turn`), which remove secrets and fence web text.

Files listed as PENDING are known gaps in files this change could not edit; each has a strict
expected-failure test, so fixing the file makes that test pass unexpectedly and fail the build
until its PENDING entry is removed.
"""

import ast
import re
from pathlib import Path

import pytest

from spyglass_service.radar.egress import LINK_ONLY_HOSTS, documented_hosts

PKG = Path(__file__).resolve().parents[2] / "src" / "spyglass_service"
RADAR = PKG / "radar"

# (a) Files allowed to build HTTP clients directly, with the reason.
CLIENT_ALLOWED = {
    "radar/netguard.py": "the page-fetch client factory itself",
    "radar/egress.py": "the model and service API client factory itself",
    "radar/netreq.py": "the guarded session for the feed library, which fetches with requests",
}
# (a) Known gaps: direct clients in files owned by other work, to be moved to the factories.
CLIENT_PENDING: dict[str, str] = {}
# (b) Files whose hosts are data, not destinations chosen in code.
HOSTS_DATA_FILES = {
    "radar/sources/seed_feeds.py": "the default feed list: each feed is a source the reader "
                                   "can remove, covered by the 'Feeds you follow' destination",
}
# (b) Top-level engine modules that send data out, scanned with the radar package.
ENGINE_MODULES = ("openrouter.py", "fetch_rungs.py", "fetch_acquire.py", "fetch_bot_check.py",
                  "documents.py", "feed_http.py", "embeddings.py", "collectors", "extractors")
# (c) The bulk seam and the provider layer it dispatches to (after the privacy step).
SEAM_MODULES = {"radar/llm.py", "radar/llm_route.py", "radar/llm_chain.py",
                "radar/llm_openai_compat.py", "radar/llm_claude.py"}
# (c) Provider calls that must only happen inside SEAM_MODULES.
PROVIDER_CALLS = {"chat_json", "claude_chat_json", "routed_chat_json", "gemini_chat_json"}
# (c) Known gap: the judging code still calls the OpenRouter client directly for that provider.
SEAM_PENDING: dict[str, str] = {}

_HTTP_CALLS = {"Client", "AsyncClient", "get", "post", "put", "patch", "delete", "head",
               "request", "stream", "options"}
_URL = re.compile(r"\b(?:https?|wss?)://([A-Za-z0-9.-]+)")


def _rel(path: Path) -> str:
    """A path relative to the package, with forward slashes (the bare name outside it)."""
    try:
        return path.relative_to(PKG).as_posix()
    except ValueError:
        return path.name


def _radar_files() -> list[Path]:
    """Every Python file of the radar package."""
    return sorted(RADAR.rglob("*.py"))


def _tree(path: Path) -> ast.Module:
    """The parsed module."""
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def direct_client_uses(path: Path) -> list[str]:
    """Places in a file that build an HTTP client or send a request without a factory."""
    found = []
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and isinstance(node.func.value, ast.Name):
            owner, attr = node.func.value.id, node.func.attr
            if (owner == "httpx" and attr in _HTTP_CALLS) or owner in ("requests", "curl_requests"):
                found.append(f"{owner}.{attr} (line {node.lineno})")
            if owner == "request" and attr == "urlopen":
                found.append(f"urllib urlopen (line {node.lineno})")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names]
            module = getattr(node, "module", None) or ""
            if module == "httpx" and set(names) & _HTTP_CALLS:
                found.append(f"from httpx import {names} (line {node.lineno})")
            if any(n.split(".")[0] in ("requests", "curl_cffi") for n in names) \
                    or module.split(".")[0] in ("curl_cffi", "requests") \
                    or module == "urllib.request":
                found.append(f"import {module or names} (line {node.lineno})")
    return found


def test_a_radar_code_builds_http_clients_only_through_the_factories() -> None:
    """No radar module creates a client or sends a request directly (outside the allowlist)."""
    offenders = {}
    for path in _radar_files():
        rel = _rel(path)
        if rel in CLIENT_ALLOWED or rel in CLIENT_PENDING:
            continue
        uses = direct_client_uses(path)
        if uses:
            offenders[rel] = uses
    assert offenders == {}, f"route these through netguard.page_client or egress.api_client: {offenders}"


@pytest.mark.parametrize("rel", sorted(CLIENT_PENDING))
@pytest.mark.xfail(strict=True, reason="known gap in a file this change could not edit")
def test_a_pending_files_use_the_factories(rel: str) -> None:
    """Fails today; passes (and so fails the build) once the file uses a factory."""
    assert direct_client_uses(PKG / rel) == []


def _string_constants(path: Path) -> list[tuple[str, int]]:
    """(text, line) of every string constant that is not a docstring."""
    tree = _tree(path)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    return [(n.value, n.lineno) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings]


def _named_hosts(path: Path) -> list[tuple[str, int]]:
    """Hosts assigned to names ending in _HOST (bare host constants)."""
    out = []
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            if any(isinstance(t, ast.Name) and t.id.endswith("_HOST") for t in node.targets):
                out.append((node.value.value, node.lineno))
    return out


def _scanned_files() -> list[Path]:
    """The radar package plus the engine modules that send data out."""
    files = list(_radar_files())
    for name in ENGINE_MODULES:
        target = PKG / name
        files += sorted(target.rglob("*.py")) if target.is_dir() else [target]
    return files


def hosts_in_code(files: list[Path] | None = None) -> dict[str, list[str]]:
    """host -> places it is named in code (docstrings excluded, data files skipped)."""
    hosts: dict[str, list[str]] = {}
    for path in files if files is not None else _scanned_files():
        rel = _rel(path)
        if rel in HOSTS_DATA_FILES:
            continue
        for text, line in _string_constants(path):
            for host in _URL.findall(text):
                hosts.setdefault(host.lower().rstrip("."), []).append(f"{rel}:{line}")
        for host, line in _named_hosts(path):
            hosts.setdefault(host.lower(), []).append(f"{rel}:{line}")
    return hosts


def test_b_every_outside_host_in_code_is_documented() -> None:
    """A host named in code but missing from the destinations table fails the build."""
    allowed = documented_hosts() | LINK_ONLY_HOSTS
    unknown = {h: where for h, where in hosts_in_code().items() if h not in allowed}
    assert unknown == {}, f"add these to radar/egress_destinations.py: {unknown}"


def seam_bypasses(path: Path) -> list[str]:
    """Direct model calls in a file: the OpenRouter client, the Claude runner, an engine stream."""
    rel, found = _rel(path), []
    for node in ast.walk(_tree(path)):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        keywords = {k.arg for k in node.keywords}
        if name in PROVIDER_CALLS and rel not in SEAM_MODULES:
            found.append(f"{name} (line {node.lineno})")
        if name == "stream" and "system" in keywords and rel != "radar/assist/threads.py":
            found.append(f"engine.stream (line {node.lineno})")
    return found


def test_c_model_calls_go_through_the_prompt_seams() -> None:
    """Outside the two seams, no radar module calls a model directly."""
    offenders = {}
    for path in _radar_files():
        rel = _rel(path)
        if rel in SEAM_PENDING:
            continue
        found = seam_bypasses(path)
        if found:
            offenders[rel] = found
    assert offenders == {}, f"call radar.llm.chat_json_for instead: {offenders}"


@pytest.mark.parametrize("rel", sorted(SEAM_PENDING))
@pytest.mark.xfail(strict=True, reason="known gap in a file this change could not edit")
def test_c_pending_files_use_the_seam(rel: str) -> None:
    """Fails today; passes (and so fails the build) once the file goes through the seam."""
    assert seam_bypasses(PKG / rel) == []


def test_c_the_seams_apply_the_privacy_step() -> None:
    """The bulk seam prepares messages and the assistant seam prepares the call."""
    llm = (RADAR / "llm.py").read_text(encoding="utf-8")
    threads = (RADAR / "assist" / "threads.py").read_text(encoding="utf-8")
    assert "prepare_bulk_messages(messages, settings)" in llm
    assert "prepare_assistant_call(" in threads


def test_the_scanners_catch_what_they_are_meant_to(tmp_path) -> None:
    """Each scanner flags a planted example, so the gate cannot pass by finding nothing."""
    planted = tmp_path / "planted.py"  # outside the source tree: parallel runs never see it
    planted.write_text('import httpx\nURL = "https://unlisted.example.net/x"\n'
                       "def f(e):\n    httpx.get(URL)\n    e.stream(system='s', messages=[])\n"
                       "    chat_json([], {}, model='m', api_key='k')\n", encoding="utf-8")
    assert direct_client_uses(planted)
    assert "unlisted.example.net" in hosts_in_code([planted])
    assert len(seam_bypasses(planted)) == 2

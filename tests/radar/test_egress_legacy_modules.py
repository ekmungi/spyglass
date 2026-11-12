"""The standing gate of `test_egress_contract`, for the modules outside `radar/`.

The older collectors and the fetch layer predate the radar package, so the first gate (which reads
only `radar/`) did not see them. This one reads every other module of the service and fails when
one of these appears without the guard:

- an httpx client built outside `netguard.guard_client(...)` / `page_client` / `api_client`;
- a direct `curl_cffi` or `requests` request, or `urlopen`;
- a feed-library reader (`make_reader`) that fetches without `use_browser_user_agent(...)`, which
  is where its HTTP session gets the address guard.

Each exception below is a file or function with the reason it needs none.
"""

import ast
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2] / "src" / "spyglass_service"

# Whole files allowed to hold a raw request, with the reason.
RAW_ALLOWED = {
    "fetch_acquire.py": "the raw curl rung; production reaches it only through "
                        "make_guarded_curl_rung, and acquire() defaults to that",
    "job_worker.py": "a probe of the reader's own Obsidian address on this computer (loopback)",
}
# Functions allowed to make a reader that does not fetch feeds (name -> reason).
READER_NO_FETCH = {
    "write_feed_health": "reads the stored state of each feed; never updates a feed",
    "delete_feed_endpoint": "deletes a feed from the reader's database; never fetches",
}
_HTTPX_CLIENTS = {"Client", "AsyncClient"}
_HTTPX_REQUESTS = {"get", "post", "put", "patch", "delete", "head", "request", "stream", "options"}
_GUARDS = {"guard_client", "page_client", "api_client"}


def _outside_radar() -> list[Path]:
    """Every module of the service except the radar package (covered by the first gate)."""
    return sorted(p for p in PKG.rglob("*.py") if "radar" not in p.relative_to(PKG).parts[:1])


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    """Child node -> parent node."""
    return {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def _call_name(node: ast.Call) -> str:
    """The called name: `f` for f(...) and `attr` for x.attr(...)."""
    func = node.func
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")


def unguarded_requests(path: Path) -> list[str]:
    """Raw requests in a module: unwrapped httpx clients, module-level httpx calls, curl, requests."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    parents, found = _parents(tree), []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and isinstance(node.func.value, ast.Name):
            owner, attr = node.func.value.id, node.func.attr
            if owner == "httpx" and attr in _HTTPX_CLIENTS:
                parent = parents.get(node)
                if not (isinstance(parent, ast.Call) and _call_name(parent) in _GUARDS) \
                        and not _assigned_then_guarded(node, parents):
                    found.append(f"httpx.{attr} outside a guard (line {node.lineno})")
            elif owner == "httpx" and attr in _HTTPX_REQUESTS:
                found.append(f"httpx.{attr} (line {node.lineno})")
            elif owner in ("requests", "curl_requests"):
                found.append(f"{owner}.{attr} (line {node.lineno})")
            elif owner == "request" and attr == "urlopen":
                found.append(f"urlopen (line {node.lineno})")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = getattr(node, "module", None) or ""
            names = [a.name.split(".")[0] for a in node.names]
            if module.split(".")[0] in ("requests", "curl_cffi") or "requests" in names:
                found.append(f"import {module or names} (line {node.lineno})")
    return found


def _assigned_then_guarded(call: ast.Call, parents: dict[ast.AST, ast.AST]) -> bool:
    """True for `client = httpx.Client(...)` whose function then returns `guard_client(client)`."""
    assign = parents.get(call)
    if not isinstance(assign, ast.Assign) or len(assign.targets) != 1 \
            or not isinstance(assign.targets[0], ast.Name):
        return False
    name = assign.targets[0].id
    scope = parents.get(assign)
    while scope is not None and not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        scope = parents.get(scope)
    return scope is not None and any(
        isinstance(n, ast.Call) and _call_name(n) in _GUARDS
        and any(isinstance(a, ast.Name) and a.id == name for a in n.args)
        for n in ast.walk(scope))


def unguarded_readers(path: Path) -> list[str]:
    """Functions that make a feed reader and never put the address guard on its session."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        calls = [n for n in ast.walk(func) if isinstance(n, ast.Call)]
        makes = any(_call_name(n) == "make_reader" for n in calls)
        guards = any(_call_name(n) == "use_browser_user_agent" for n in calls)
        if makes and not guards and func.name not in READER_NO_FETCH:
            found.append(f"{func.name} (line {func.lineno})")
    return found


def test_no_older_module_sends_a_raw_request() -> None:
    """Outside the allowlist, no module outside `radar/` builds an unguarded client or request."""
    offenders = {}
    for path in _outside_radar():
        rel = path.relative_to(PKG).as_posix()
        if rel in RAW_ALLOWED:
            continue
        found = unguarded_requests(path)
        if found:
            offenders[rel] = found
    assert offenders == {}, f"route these through netguard.page_client / guard_client: {offenders}"


def test_every_feed_reader_that_fetches_gets_the_guard() -> None:
    """Every reader made to update feeds goes through `use_browser_user_agent` (the guard's home)."""
    offenders = {}
    for path in _outside_radar():
        found = unguarded_readers(path)
        if found:
            offenders[path.relative_to(PKG).as_posix()] = found
    assert offenders == {}, f"call feed_http.use_browser_user_agent(reader) on these: {offenders}"


def test_the_allowlists_name_files_that_exist() -> None:
    """A stale allowlist entry (a renamed file) would silently allow nothing; fail instead."""
    for rel in RAW_ALLOWED:
        assert (PKG / rel).is_file(), rel
    names = {n.name for p in _outside_radar() for n in ast.walk(ast.parse(p.read_text("utf-8")))
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert set(READER_NO_FETCH) <= names


@pytest.mark.parametrize("source", [
    "import httpx\ndef f():\n    return httpx.Client(timeout=5)\n",
    "import httpx\ndef f(u):\n    return httpx.get(u)\n",
    "from curl_cffi import requests\ndef f(u):\n    return requests.get(u)\n",
])
def test_the_request_scanner_catches_planted_examples(tmp_path, source) -> None:
    """Each planted bypass is flagged, so the gate cannot pass by finding nothing."""
    planted = tmp_path / "planted.py"
    planted.write_text(source, encoding="utf-8")
    assert unguarded_requests(planted)


def test_the_request_scanner_accepts_a_guarded_client(tmp_path) -> None:
    """A client wrapped in guard_client, or returned from a function that wraps it, is fine."""
    ok = tmp_path / "ok.py"
    ok.write_text("import httpx\nfrom x import guard_client\n"
                  "def a():\n    return guard_client(httpx.Client())\n"
                  "def b():\n    c = httpx.Client()\n    return guard_client(c)\n", encoding="utf-8")
    assert unguarded_requests(ok) == []


def test_the_reader_scanner_catches_an_unguarded_reader(tmp_path) -> None:
    """A function that makes a reader without the guard is flagged; a guarded one is not."""
    bad = tmp_path / "bad.py"
    bad.write_text("def f():\n    return make_reader('x')\n", encoding="utf-8")
    good = tmp_path / "good.py"
    good.write_text("def f():\n    r = make_reader('x')\n    use_browser_user_agent(r)\n",
                    encoding="utf-8")
    assert unguarded_readers(bad) and unguarded_readers(good) == []

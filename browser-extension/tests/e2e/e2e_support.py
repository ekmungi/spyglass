"""Helpers for run_e2e.py: the test copy of the extension, the fixture web pages and a stub Spyglass.

Nothing here touches the reader's own browsers. It only builds files in a temporary folder and
starts two small web servers on 127.0.0.1 for the length of one run.
"""

import asyncio
import json
import shutil
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# The host name the test browser maps to the fixture server. Spyglass checks an address by its
# form only (no lookup), so this reads as a public site while the page comes from this computer.
FIXTURE_HOST = "fixtures.example.org"

# Wraps the extension's own listeners so a test can call them as the browser would, and records
# the desktop notifications the extension asks for. Used in the test copy only.
INSTRUMENT_JS = """
// Test-only: record listeners and notifications; the shipped extension has none of this.
const log = (globalThis.__e2e = { menu: [], command: [], notifications: [], errors: [] })
function remember(event, list) {
  const original = event.addListener.bind(event)
  Object.defineProperty(event, 'addListener', {
    value: (listener) => { list.push(listener); original(listener) }, configurable: true, writable: true,
  })
}
remember(chrome.contextMenus.onClicked, log.menu)
remember(chrome.commands.onCommand, log.command)
const createNotification = chrome.notifications.create.bind(chrome.notifications)
chrome.notifications.create = (options) => new Promise((resolve) => {
  createNotification(options, (id) => {
    const error = chrome.runtime.lastError ? chrome.runtime.lastError.message : null
    log.notifications.push({ title: options.title, message: options.message, error, id })
    resolve(id)
  })
})
self.addEventListener('error', (event) => log.errors.push(String(event.message)))
self.addEventListener('unhandledrejection', (event) => log.errors.push(String(event.reason)))
"""

SKIP_DIRS = {"tests", "tools", "node_modules"}


def make_test_copy(source: Path, target: Path) -> None:
    """Copy the extension to `target` with two test-only changes: it may read any page without a
    click (`<all_urls>`), and its service worker loads the recording wrapper first."""
    shutil.copytree(source, target, ignore=lambda _d, names: [n for n in names if n in SKIP_DIRS])
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    manifest["host_permissions"] = ["<all_urls>", *manifest["host_permissions"]]
    manifest["background"]["service_worker"] = "bg_test.js"
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (target / "instrument.js").write_text(INSTRUMENT_JS, encoding="utf-8")
    (target / "bg_test.js").write_text("import './instrument.js'\nimport './background.js'\n", encoding="utf-8")


def _words(seed: str, count: int) -> str:
    """Plain filler sentences that read like prose, so the article extractor keeps them."""
    sentence = (f"The {seed} survey describes how readers keep a small collection of sources, "
                "compare what each one claims, and decide which of them deserves a second look. ")
    return (sentence * (count // 25 + 1)).strip()


def article_page(title: str, marker: str, paragraphs: int = 14) -> str:
    """A long article inside heavy navigation: 400 links above it, a sidebar and a footer."""
    nav = "".join(f'<li><a href="/n{i}">NAVJUNK menu entry {i}</a></li>' for i in range(400))
    body = "".join(f"<p>{marker} paragraph {i}. {_words(marker, 70)}</p>" for i in range(paragraphs))
    return (f"<!doctype html><html><head><meta charset=utf-8><title>{title}</title></head><body>"
            f"<header><nav><ul>{nav}</ul></nav></header>"
            f"<aside>NAVJUNK related links and an advertisement</aside>"
            f"<article><h1>{title}</h1>{body}</article>"
            f"<footer>NAVJUNK copyright and cookie notice</footer></body></html>")


SELECTION_PAGE = (
    "<!doctype html><html><head><meta charset=utf-8><title>Selection target</title></head><body>"
    "<nav>NAVJUNK</nav><article><h1>Selection target</h1>"
    "<p>An opening paragraph before the part that gets selected.</p>"
    "<p id=start>SELECTMARK this sentence has <strong>bold words</strong>, <em>slanted words</em> and "
    '<a href="https://example.org/ref">a link</a>.</p>'
    "<ul id=end><li>first listed point SELECTMARK</li><li>second listed point</li></ul>"
    "<p>A closing paragraph after the part that gets selected.</p></article></body></html>")

BIG_FILL = "<div>" + "x" * 60 + "</div>\n"


def big_page(with_article: bool) -> str:
    """A page of about 7 MB: junk markup, plus (optionally) a short real <article>."""
    junk = BIG_FILL * (7 * 1024 * 1024 // len(BIG_FILL))
    article = ("<article><h1>Big page article</h1>"
               + "".join(f"<p>BIGARTICLE {i}. {_words('big', 70)}</p>" for i in range(10)) + "</article>"
               if with_article else "")
    return f"<!doctype html><html><head><meta charset=utf-8><title>Big page</title></head><body>{junk}{article}</body></html>"


PDF_BYTES = (b"%PDF-1.1\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
             b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R/Size 4>>\n%%EOF\n")


class FixtureHandler(BaseHTTPRequestHandler):
    """Serves the fixture pages by path."""

    def log_message(self, *_args) -> None:  # keep the test output quiet
        pass

    def do_GET(self) -> None:  # noqa: N802 (http.server naming)
        path = self.path.split("?")[0]
        pages = {
            "/article-long": ("text/html", article_page("The long fixture article", "ZEPHYRARTICLE").encode()),
            "/article-twice": ("text/html", article_page("The twice-sent article", "TWICEARTICLE").encode()),
            "/selection-first": ("text/html", SELECTION_PAGE.encode()),
            "/selection-after-page": ("text/html", SELECTION_PAGE.replace("Selection target", "Selection after page").encode()),
            "/big-article": ("text/html", big_page(True).encode()),
            "/big-nomain": ("text/html", big_page(False).encode()),
            "/doc.pdf": ("application/pdf", PDF_BYTES),
            "/paper": ("application/pdf", PDF_BYTES),
        }
        if path not in pages:
            self.send_error(404)
            return
        kind, data = pages[path]
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class StubState:
    """What the stub Spyglass was asked, and how it should answer next."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.mode = "ok"  # ok | hang | too-many
        self.stop = threading.Event()


def stub_handler(state: StubState):
    """A request handler class that records each request and answers as `state.mode` says."""

    class Stub(BaseHTTPRequestHandler):
        def log_message(self, *_args) -> None:
            pass

        def _answer(self, status: int, payload: dict) -> None:
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _record(self, body: bytes) -> dict:
            entry = {"method": self.command, "path": self.path, "origin": self.headers.get("Origin"),
                     "has_key": bool(self.headers.get("X-Spyglass-Key")), "type": self.headers.get("Content-Type"),
                     "bytes": len(body), "time": time.time()}
            if body:
                try:
                    parsed = json.loads(body)
                    html = parsed.get("html")
                    entry.update(url=parsed.get("url"), kind=parsed.get("kind"), note=parsed.get("note"),
                                 html_chars=len(html) if html is not None else None,
                                 html_head=(html or "")[:80], text=parsed.get("text"), title=parsed.get("title"))
                except ValueError:
                    entry["unparsed"] = True
            state.requests.append(entry)
            return entry

        def do_OPTIONS(self) -> None:  # noqa: N802
            self._record(b"")
            self.send_response(204)
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            self._record(b"")
            self._answer(200, {"ok": True, "app": "stub"})

        def do_POST(self) -> None:  # noqa: N802
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            self._record(body)
            if state.mode == "hang":
                state.stop.wait(60)
                return
            if state.mode == "too-many":
                self._answer(429, {"detail": "Too many pages were sent in a short time. Wait a few minutes and try again."})
                return
            self._answer(200, {"item_id": 424242, "title": "stub", "words": 1, "replaced": False})

    return Stub


class QuietServer(ThreadingHTTPServer):
    """A server that ignores connections the browser drops half way (normal for a closed tab)."""

    def handle_error(self, request, client_address) -> None:
        pass


def serve(handler, port: int = 0) -> tuple[ThreadingHTTPServer, int]:
    """Start `handler` on 127.0.0.1 in a thread; returns the server and the port it got."""
    server = QuietServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


# ---- shared helpers for the runner and the layers ----

EXTENSION = Path(__file__).resolve().parents[2]
CLOSED_PORT = 7999  # nothing listens here, so it stands for "Spyglass is not running"
WIKI = "https://en.wikipedia.org/wiki/Information_retrieval"
ARXIV = "https://arxiv.org/abs/1706.03762"
WRONG_KEY = "a" * 32
KEY_MESSAGE = "The key is missing or wrong. Open the extension's settings."


class Report:
    """Collects (check, layer, passed, evidence) rows and prints them as a table."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, int, bool, str]] = []
        self.ids: list[int] = []  # items created in Spyglass by the run

    def add(self, name: str, layer: int, passed: bool, evidence: str) -> None:
        self.rows.append((name, layer, bool(passed), evidence.replace("\n", " ")[:260]))
        print(f"[{'PASS' if passed else 'FAIL'}] L{layer} {name}: {self.rows[-1][3]}", flush=True)

    def summary(self) -> int:
        failed = [r for r in self.rows if not r[2]]
        print(f"\n{len(self.rows) - len(failed)} passed, {len(failed)} failed")
        return 1 if failed else 0


def strings_of(value) -> str:
    """Every string inside a JSON value, joined; lets a check look for text without knowing the shape."""
    if isinstance(value, str):
        return value + "\n"
    if isinstance(value, dict):
        return "".join(strings_of(v) for v in value.values())
    if isinstance(value, list):
        return "".join(strings_of(v) for v in value)
    return ""


def http_json(url: str, headers: dict | None = None):
    """GET a JSON answer, or the status code and body text of an error."""
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")


async def launch(playwright, extension: Path, profile: Path):
    """Start Chromium with `extension` loaded, in a small visible window."""
    return await playwright.chromium.launch_persistent_context(
        str(profile), headless=False, viewport=None, ignore_default_args=["--disable-extensions"],
        args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}",
              f"--host-resolver-rules=MAP {FIXTURE_HOST} 127.0.0.1", "--window-size=1000,760",
              "--window-position=40,40", "--no-first-run"])


async def evaluate(page, expression: str, arg=None):
    """Run JavaScript in the page's own world (the extension API is not in the isolated one)."""
    return await page.evaluate(expression, arg, isolated_context=False)


async def extension_id(ctx) -> str:
    """The id Chromium gave the unpacked extension, read from its service worker's address."""
    worker = ctx.service_workers[0] if ctx.service_workers else await ctx.wait_for_event("serviceworker", timeout=15000)
    return worker.url.split("/")[2]


async def options_page(ctx, ext_id: str):
    """The settings page: the one opened by the first install, or a new one."""
    for _ in range(100):
        for page in ctx.pages:
            if page.url == f"chrome-extension://{ext_id}/options.html":
                return page, True
        await asyncio.sleep(0.25)
    page = await ctx.new_page()
    await page.goto(f"chrome-extension://{ext_id}/options.html")
    return page, False




async def runtime_report(ctx, ext_id: str) -> dict:
    """Manifest errors, install warnings and runtime errors as chrome://extensions would list them."""
    page = await ctx.new_page()
    await page.goto("chrome://extensions")
    info = await evaluate(page, """async (id) => {
      const list = await chrome.developerPrivate.getExtensionsInfo({includeDisabled: true});
      const e = list.find((x) => x.id === id);
      return {manifestErrors: e.manifestErrors.map((m) => m.message), installWarnings: e.installWarnings.map((w) => w.message),
              runtimeErrors: e.runtimeErrors.map((r) => r.message), runtimeWarnings: e.runtimeWarnings,
              commands: e.commands.map((c) => c.name + '=' + c.keybinding + ' active=' + c.isActive)};
    }""", ext_id)
    await page.close()
    return info

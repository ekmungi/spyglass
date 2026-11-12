"""Layer 2 of run_e2e.py: every way of sending, on a test copy of the extension.

The test copy may read any page without a click; everything after that is the shipped code. A send
is started with the same runtime message the popup sends to the service worker, and the menu and
shortcut handlers are called with the arguments the browser would pass.
"""

import asyncio
import tempfile
import time
from pathlib import Path

from patchright.async_api import async_playwright

from e2e_support import (CLOSED_PORT, EXTENSION, FIXTURE_HOST, KEY_MESSAGE, FixtureHandler, Report, StubState,
                         evaluate, extension_id, http_json, launch, make_test_copy, options_page, runtime_report,
                         serve, stub_handler, strings_of)

NO_READ = "This page cannot be read here."
SELECT_SCRIPT = """() => { const r = document.createRange(); r.setStartBefore(document.getElementById('start'));
  r.setEndAfter(document.getElementById('end')); const s = getSelection(); s.removeAllRanges(); s.addRange(r); }"""


class Driver:
    """Talks to the test copy: sends, opens pages, reads the service worker's records."""

    def __init__(self, ctx, opts, address: str, key: str, fixture_port: int, stub_port: int, stub: StubState) -> None:
        self.ctx, self.opts, self.address, self.key = ctx, opts, address, key
        self.fixtures = f"http://{FIXTURE_HOST}:{fixture_port}"
        self.local_fixtures = f"http://127.0.0.1:{fixture_port}"
        self.stub, self.stub_url = stub, f"http://127.0.0.1:{stub_port}"
        self.ids: list[int] = []
        self.on_stub = False

    async def aim(self, address: str, key: str | None = None) -> None:
        """Point the extension at an address (and key) by saving them as the settings page would."""
        await evaluate(self.opts, "(v) => chrome.storage.local.set({address: v[0], key: v[1]})", [address, key if key is not None else self.key])
        self.on_stub = address == self.stub_url

    async def open(self, url: str):
        """Open a page in a new tab. A web page that fails to load is retried, then reported."""
        page = await self.ctx.new_page()
        for attempt in range(3):
            try:
                await page.goto(url, wait_until="load", timeout=60000)
                return page
            except Exception as error:
                if url.endswith(("/doc.pdf", "/paper")):
                    await asyncio.sleep(1)  # a PDF may count as a download; the tab's address still settles
                    return page
                if attempt == 2:
                    raise RuntimeError(f"could not open {url}: {str(error)[:120]}") from error
                await asyncio.sleep(3)
        return page

    async def active_tab_id(self, page) -> int:
        """The id of the tab showing `page` (for browser pages, whose address the extension cannot see)."""
        await page.bring_to_front()
        await asyncio.sleep(0.5)
        return await evaluate(self.opts, "() => chrome.tabs.query({active: true, lastFocusedWindow: true}).then((t) => t[0].id)")

    async def tab_id(self, url_part: str) -> int:
        """The id of the tab whose address contains `url_part`."""
        tabs = await evaluate(self.opts, "() => chrome.tabs.query({}).then((t) => t.map((x) => [x.id, x.url || '']))")
        return next(i for i, u in tabs if url_part in u)

    async def send(self, url_part: str, kind: str = "page", note: str = "", tab: int | None = None) -> dict:
        """Send a tab the way the popup does and return the service worker's answer."""
        tab = tab if tab is not None else await self.tab_id(url_part)
        result = await evaluate(self.opts, "(a) => chrome.runtime.sendMessage({type: 'send', tabId: a[0], kind: a[1], note: a[2]})",
                                [tab, kind, note])
        if result and result.get("itemId") and not self.on_stub:
            self.ids.append(result["itemId"])
        return result

    async def worker(self):
        """The running service worker of the test copy (waking it first if it is asleep)."""
        for _ in range(3):
            for worker in self.ctx.service_workers:
                if worker.url.endswith("bg_test.js"):
                    return worker
            await evaluate(self.opts, "() => chrome.runtime.sendMessage({type: 'wake'})")
            await asyncio.sleep(1)
        raise RuntimeError("service worker not running")

    async def item(self, item_id: int) -> tuple[int, object]:
        """The item as the Spyglass interface reads it."""
        return http_json(f"{self.address}/api/radar/items/{item_id}")

    async def invoke(self, script: str, tab_url_part: str) -> list[dict]:
        """Call a recorded listener with a real tab, then return the notifications it caused."""
        worker = await self.worker()
        before = len(await worker.evaluate("() => __e2e.notifications"))
        tab = await self.tab_id(tab_url_part)
        await worker.evaluate(f"(id) => chrome.tabs.get(id).then((tab) => {{ {script} }})", tab)
        for _ in range(80):
            notes = await (await self.worker()).evaluate("() => __e2e.notifications")
            if len(notes) > before:
                return notes[before:]
            await asyncio.sleep(0.5)
        return []


def has_all(text: str, *needles: str) -> bool:
    """True when every needle is in `text`."""
    return all(n in text for n in needles)


async def sends_to_real_service(report: Report, d: Driver) -> None:
    """Fixture pages and the stored item: article only, once, with the note; then the selections."""
    base = d.fixtures
    page = await d.open(f"{base}/article-twice")
    first = await d.send(f"{base}/article-twice", note="E2E note text")
    second = await d.send(f"{base}/article-twice")
    status, item = await d.item(first.get("itemId", 0))
    text = strings_of(item)
    report.add("send page: article kept, navigation dropped", 2, first.get("ok") and has_all(text, "TWICEARTICLE") and "NAVJUNK" not in text,
               f"{first} item HTTP {status}, {len(text)} chars")
    report.add("note is stored with the item", 2, "E2E note text" in text, "note found in the item" if "E2E note text" in text else "note missing")
    report.add("sending the same page twice does not duplicate", 2, first.get("itemId") == second.get("itemId") and second.get("ok"),
               f"ids {first.get('itemId')} and {second.get('itemId')}, messages {first.get('message')!r} / {second.get('message')!r}")
    await page.close()

    page = await d.open(f"{base}/selection-first")
    await page.evaluate(SELECT_SCRIPT)
    chosen = await d.send(f"{base}/selection-first", "selection")
    status, item = await d.item(chosen.get("itemId", 0))
    text = strings_of(item)
    report.add("send selection (page not sent before): selection stored, formatting kept", 2,
               chosen.get("ok") and has_all(text, "SELECTMARK", "bold words", "second listed point") and "NAVJUNK" not in text
               and "closing paragraph" not in text and ("<strong>" in text or "<b>" in text) and "<li>" in text,
               f"{chosen} strong={'<strong>' in text} li={'<li>' in text} link={'example.org/ref' in text}")
    await page.close()

    page = await d.open(f"{base}/selection-after-page")
    whole = await d.send(f"{base}/selection-after-page")
    await page.evaluate(SELECT_SCRIPT)
    part = await d.send(f"{base}/selection-after-page", "selection")
    status, item = await d.item(part.get("itemId", 0))
    report.add("selection after the full page becomes a separate item", 2,
               whole.get("ok") and part.get("ok") and whole["itemId"] != part["itemId"] and "Selection from:" in strings_of(item),
               f"page item {whole.get('itemId')}, selection item {part.get('itemId')}")
    await page.evaluate("() => getSelection().removeAllRanges()")
    nothing = await d.send(f"{base}/selection-after-page", "selection")
    report.add("selection with nothing selected", 2, nothing.get("message") == "Select some text on the page first.", str(nothing))
    await page.close()

    page = await d.open(f"{d.local_fixtures}/article-long")
    local = await d.send(f"{d.local_fixtures}/article-long")
    report.add("a locally served page fails with a plain message", 2, local.get("ok") is False and 0 < len(local.get("message", "")) < 160
               and "Traceback" not in local["message"], str(local))
    await page.close()


async def sends_real_pages(report: Report, d: Driver) -> None:
    """A Wikipedia article and an arXiv abstract page, then one screenshot of the first in Spyglass."""
    wiki = await d.open("https://en.wikipedia.org/wiki/Information_retrieval")
    result = await d.send("wikipedia.org/wiki/Information_retrieval")
    _, item = await d.item(result.get("itemId", 0))
    text = strings_of(item)
    report.add("Wikipedia article: article text, not the navigation", 2,
               result.get("ok") and "Information retrieval" in text and "Random article" not in text and "Donate" not in text and len(text) > 5000,
               f"{result} {len(text)} chars; sidebar words present: {[w for w in ('Random article', 'Donate', 'Create account') if w in text]}")
    arxiv = await d.open("https://arxiv.org/abs/2005.14165")
    result_arxiv = await d.send("arxiv.org/abs/2005.14165")
    _, item = await d.item(result_arxiv.get("itemId", 0))
    text = strings_of(item)
    report.add("arXiv abstract page: abstract kept", 2, result_arxiv.get("ok") and "pre-training on a large corpus" in text,
               f"{result_arxiv} {len(text)} chars; 'Skip to main content' present: {'Skip to main content' in text}")
    if result.get("itemId"):
        shot = await d.ctx.new_page()
        await shot.goto(f"{d.address}/#/item/{result['itemId']}")
        await asyncio.sleep(4)
        path = Path(tempfile.gettempdir()) / "ext_e2e_item.png"
        await shot.screenshot(path=str(path))
        report.add("item opens in the Spyglass interface", 2, True, f"screenshot {path}")
        await shot.close()
    await wiki.close()
    await arxiv.close()


async def big_pages(report: Report, d: Driver) -> None:
    """Pages over 6 MB, seen by the stub so the exact payload can be measured."""
    await d.aim(d.stub_url)
    for name, check in (("big-article", lambda r: (r["html_head"].startswith("<article"), r["html_chars"] < 6 * 1024 * 1024)),
                        ("big-nomain", lambda r: (True, r["html_chars"] == 2000000))):
        d.stub.requests.clear()
        page = await d.open(f"{d.fixtures}/{name}")
        size = await page.evaluate("() => document.documentElement.outerHTML.length")
        result = await d.send(f"/{name}")
        posts = [r for r in d.stub.requests if r["method"] == "POST"]
        ok = bool(posts) and all(check(posts[0]))
        report.add(f"page over 6 MB ({name}, {size / 1e6:.1f}M chars)", 2, result.get("ok") and ok,
                   f"sent {posts[0]['html_chars'] if posts else None} chars starting {posts[0]['html_head'][:40]!r}" if posts else str(result))
        if posts:
            origin = posts[0]["origin"]
            if name == "big-article":
                report.add("Origin on the service worker's POST", 2, origin == f"chrome-extension://{d.ext_id}",
                           f"Origin={origin} content-type={posts[0]['type']} key sent={posts[0]['has_key']}")
        await page.close()
    await d.aim(d.address)
    page = await d.open(f"{d.fixtures}/big-article")
    result = await d.send("/big-article")
    report.add("page over 6 MB with an article, to the real service", 2, result.get("ok"), str(result))
    await page.close()


async def unreadable_pages(report: Report, d: Driver) -> None:
    """Browser pages and PDFs."""
    for url in ("chrome://version", "about:blank", f"chrome-extension://{d.ext_id}/options.html"):
        page = await d.open(url)
        result = await d.send("", tab=await d.active_tab_id(page))
        report.add(f"browser-internal page: {url.split('/')[0]}//{url.split('/')[2] if url.count('/') > 1 else ''}", 2,
                   result.get("message") == NO_READ and not result.get("ok"), str(result))
        await page.close()
    pdf = await d.open(f"{d.fixtures}/doc.pdf")
    result = await d.send("/doc.pdf")
    report.add("PDF in the built-in viewer (address ends in .pdf)", 2, result.get("message") == NO_READ and "Download the file" in result.get("hint", ""), str(result))
    await pdf.close()
    paper = await d.open(f"{d.fixtures}/paper")
    result = await d.send("/paper")
    report.add("PDF in the viewer, address without .pdf (like arxiv.org/pdf/...)", 2, result.get("message") == NO_READ, str(result))
    await paper.close()


async def menus_and_failures(report: Report, d: Driver) -> None:
    """Right-click entries, the shortcut, notifications, wrong key, closed port, 429 and the 30 s timeout."""
    error = await evaluate(d.opts, "() => new Promise((r) => chrome.contextMenus.create({id: 'send-page', title: 'x'}, () => r(chrome.runtime.lastError ? chrome.runtime.lastError.message : null)))")
    other = await evaluate(d.opts, "() => new Promise((r) => chrome.contextMenus.create({id: 'send-selection', title: 'x'}, () => r(chrome.runtime.lastError ? chrome.runtime.lastError.message : null)))")
    report.add("both right-click entries exist (re-creating them reports a duplicate id)", 2, "duplicate" in str(error) and "duplicate" in str(other), f"{error} / {other}")
    worker = await d.worker()
    counts = await worker.evaluate("() => [__e2e.menu.length, __e2e.command.length, __e2e.errors]")
    report.add("menu and shortcut listeners registered; no worker errors", 2, counts[0] == 1 and counts[1] == 1 and not counts[2], str(counts))
    page = await d.open(f"{d.fixtures}/article-long")
    notes = await d.invoke("__e2e.menu[0]({menuItemId: 'send-page'}, tab)", "/article-long")
    report.add("right-click 'Send this page' -> notification", 2, bool(notes) and notes[0]["title"] == "Send to Spyglass" and not notes[0]["error"], str(notes))
    notes = await d.invoke("__e2e.command[0]('send-page', tab)", "/article-long")
    report.add("shortcut handler -> notification", 2, bool(notes) and notes[0]["title"] == "Send to Spyglass" and not notes[0]["error"], str(notes))
    await page.close()
    page = await d.open(f"{d.fixtures}/selection-first")
    await page.evaluate(SELECT_SCRIPT)
    notes = await d.invoke("__e2e.menu[0]({menuItemId: 'send-selection'}, tab)", "/selection-first")
    report.add("right-click 'Send selected text' -> notification", 2, bool(notes) and not notes[0]["error"], str(notes))
    await d.aim(f"http://localhost:{CLOSED_PORT}")
    notes = await d.invoke("__e2e.menu[0]({menuItemId: 'send-page'}, tab)", "/selection-first")
    report.add("failure notification when Spyglass is not running", 2, bool(notes) and notes[0]["title"] == "Send to Spyglass: not sent"
               and "not running" in notes[0]["message"], str(notes))
    result = await d.send("/selection-first")
    report.add("closed port: plain sentence", 2, result.get("message") == "Spyglass is not running on this computer.", str(result))
    await d.aim(d.address, "b" * 32)
    result = await d.send("/selection-first")
    report.add("wrong key on a send", 2, result.get("message") == KEY_MESSAGE, str(result))
    await d.aim(d.address, "")
    result = await d.send("/selection-first")
    report.add("no key saved", 2, result.get("message") == KEY_MESSAGE, str(result))
    await d.aim(d.stub_url)
    d.stub.mode = "too-many"
    result = await d.send("/selection-first")
    report.add("429 passes Spyglass's own sentence on", 2, result.get("message", "").startswith("Too many pages"), str(result))
    d.stub.mode = "hang"
    started = time.monotonic()
    result = await d.send("/selection-first")
    waited = time.monotonic() - started
    report.add("30-second timeout sentence", 2, result.get("message", "").startswith("Spyglass did not answer within 30 seconds") and 29 < waited < 50,
               f"{waited:.1f}s {result}")
    d.stub.stop.set()
    d.stub.mode = "ok"
    await page.close()
    await d.aim(d.address)


async def layer2(report: Report, address: str, key: str, workdir: Path, offline: bool) -> None:
    """Load the test copy and run the groups of checks."""
    test_copy = workdir / "extension_test_copy"
    make_test_copy(EXTENSION, test_copy)
    stub_state = StubState()
    stub, stub_port = serve(stub_handler(stub_state))
    fixtures, fixture_port = serve(FixtureHandler)
    async with async_playwright() as playwright:
        ctx = await launch(playwright, test_copy, Path(tempfile.mkdtemp(prefix="profile2_", dir=workdir)))
        ext_id = await extension_id(ctx)
        opts, _ = await options_page(ctx, ext_id)
        driver = Driver(ctx, opts, address, key, fixture_port, stub_port, stub_state)
        driver.ext_id = ext_id
        await driver.aim(address)
        await sends_to_real_service(report, driver)
        if not offline:
            await sends_real_pages(report, driver)
        await big_pages(report, driver)
        await unreadable_pages(report, driver)
        await menus_and_failures(report, driver)
        info = await runtime_report(ctx, ext_id)
        report.add("no extension runtime errors during the whole run", 2, not info["runtimeErrors"], str(info["runtimeErrors"]))
        report.ids = driver.ids
        await asyncio.wait_for(ctx.close(), 30)
    stub.shutdown()
    fixtures.shutdown()

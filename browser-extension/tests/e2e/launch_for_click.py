"""Layer 3 helper: open the SHIPPED extension in a test Chromium so a person (or a desktop-automation
tool) can make one real click on the toolbar button or press Alt+Shift+S.

    uv run python browser-extension/tests/e2e/launch_for_click.py --address http://localhost:7778

It saves the address and the key (read from the service, never printed) as the settings page would,
opens a Wikipedia article, prints the window's profile folder, and stays open until the file named
"stop" appears in that folder (or 20 minutes pass). Nothing is clicked here: the click is the point.
"""

import argparse
import asyncio
import sys
import tempfile
import time
from pathlib import Path

from patchright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).parent))
from e2e_support import EXTENSION, evaluate, extension_id, http_json, launch, options_page  # noqa: E402

ARTICLE = "https://en.wikipedia.org/wiki/Web_browser"


async def main() -> int:
    """Launch, configure, wait for the stop file."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", required=True)
    parser.add_argument("--url", default=ARTICLE)
    args = parser.parse_args()
    status, body = http_json(f"{args.address.rstrip('/')}/api/radar/import/button-key")
    if status != 200:
        print(f"Could not read the key (HTTP {status}).")
        return 2
    work = Path(tempfile.mkdtemp(prefix="ext_click_"))
    async with async_playwright() as playwright:
        ctx = await launch(playwright, EXTENSION, work / "profile")
        ext_id = await extension_id(ctx)
        opts, _ = await options_page(ctx, ext_id)
        await evaluate(opts, "(v) => chrome.storage.local.set({address: v[0], key: v[1]})", [args.address.rstrip("/"), body["key"]])
        page = await ctx.new_page()
        await page.goto(args.url)
        await opts.close()
        print(f"READY extension={ext_id} folder={work} title={await page.title()!r}", flush=True)
        deadline = time.monotonic() + 1200
        while time.monotonic() < deadline and not (work / "stop").exists():
            await asyncio.sleep(1)
        await ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

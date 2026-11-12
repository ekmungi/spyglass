"""End-to-end test of the "Send to Spyglass" extension in a real (headed) Chromium.

Run from the repository root, with Spyglass already running (the test creates items in it):

    uv run python browser-extension/tests/e2e/run_e2e.py --address http://localhost:7778

Layer 1 loads the shipped, unmodified extension and checks it installs, connects and refuses bad
settings. Layer 2 loads a temporary copy that may read any page without a click (automation cannot
click the toolbar button) and drives every send path through the same message the popup sends.
Layer 3 (one real toolbar click) cannot be automated here and is done by hand; see the README.

Uses only the Chromium that patchright already installed, with a throwaway profile in a temporary
folder. The key is read from the service itself and is never printed. Needs network access for the
Wikipedia and arXiv checks (skip them with --offline). Exit code 0 when every check passes.

Spyglass accepts at most 30 imports in ten minutes and a full run sends about 15, so wait ten
minutes between runs (a 429 "Too many pages" in the output means the allowance was used up).
"""

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

from patchright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).parent))
from e2e_support import (CLOSED_PORT, EXTENSION, KEY_MESSAGE, WRONG_KEY, Report, StubState, evaluate,  # noqa: E402
                         extension_id, http_json, launch, options_page, runtime_report, serve, stub_handler)

async def fill_and_test(page, address: str, key: str) -> str:
    """Type the address and key into the settings form, press Test connection, return the message."""
    await page.fill("#address", address)
    await page.fill("#key", key)
    await page.click("#test")
    await page.wait_for_function("() => { const t = document.getElementById('status').textContent; return t && t !== 'Testing…' }")
    return (await page.inner_text("#status")).strip()


async def layer1(report: Report, address: str, key: str, workdir: Path) -> None:
    """The shipped extension: loads cleanly, opens settings, connects, refuses bad settings."""
    state = StubState()
    stub, stub_port = serve(stub_handler(state))
    async with async_playwright() as playwright:
        ctx = await launch(playwright, EXTENSION, Path(tempfile.mkdtemp(prefix="profile1_", dir=workdir)))
        ext_id = await extension_id(ctx)
        info = await runtime_report(ctx, ext_id)
        clean = not (info["manifestErrors"] or info["installWarnings"] or info["runtimeErrors"] or info["runtimeWarnings"])
        report.add("loads with no manifest error or warning", 1, clean, json.dumps(info))
        page, opened_by_install = await options_page(ctx, ext_id)
        report.add("settings page opens on first install", 1, opened_by_install, page.url)
        message = await fill_and_test(page, address, key)
        report.add("save + Test connection with the right key", 1, message == "Saved. Connected to Spyglass", message)
        await page.reload()
        await page.wait_for_function("() => document.getElementById('key').value.length === 32")
        report.add("settings survive a reload", 1, await page.input_value("#address") == address, "address and a 32-character key are back")
        message = await fill_and_test(page, address, WRONG_KEY)
        report.add("wrong key gives the plain sentence", 1, message == KEY_MESSAGE, message)
        message = await fill_and_test(page, f"http://localhost:{CLOSED_PORT}", key)
        report.add("stopped address gives the plain sentence", 1, message == "Spyglass is not running on this computer.", message)
        message = await fill_and_test(page, address, "not-a-key")
        report.add("malformed key refused by the form", 1, message.startswith("That does not look like the key"), message)
        for bad in ("http://example.com:7777", "https://localhost:7778", "http://localhost", "http://localhost.evil.com:7778"):
            message = await fill_and_test(page, bad, key)
            report.add(f"non-local address refused: {bad}", 1, message.startswith("Use an address like"), message)
        message = await fill_and_test(page, f"http://127.0.0.1:{stub_port}", key)
        origins = {r["origin"] for r in state.requests}
        # A GET from the settings page carries no Origin header at all (Chromium omits it for
        # an extension page with host access); the POST from the service worker is checked in layer 2.
        report.add("Origin on the settings page's GET", 1, origins <= {None, f"chrome-extension://{ext_id}"} and message.endswith("Connected to Spyglass"),
                   f"origin={sorted(map(str, origins))} methods={[r['method'] for r in state.requests]} has_key={[r['has_key'] for r in state.requests]}")
        status, _ = http_json(f"{address}/api/radar/import/direct/check", {"X-Spyglass-Key": key, "Origin": f"chrome-extension://{ext_id}"})
        report.add("route accepts that Origin", 1, status == 200, f"HTTP {status}")
        status, _ = http_json(f"{address}/api/radar/import/direct/check", {"X-Spyglass-Key": key, "Origin": "https://evil.example"})
        report.add("route refuses a web page Origin", 1, status == 403, f"HTTP {status}")
        await asyncio.wait_for(ctx.close(), 30)
    stub.shutdown()


async def main() -> int:
    """Run the layers and print the table."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--address", required=True, help="where Spyglass listens, e.g. http://localhost:7778")
    parser.add_argument("--layers", default="1,2", help="comma-separated layers to run (default 1,2)")
    parser.add_argument("--offline", action="store_true", help="skip the Wikipedia and arXiv checks")
    args = parser.parse_args()
    address = args.address.rstrip("/")
    status, body = http_json(f"{address}/api/radar/import/button-key")
    if status != 200 or not isinstance(body, dict) or not body.get("key"):
        print(f"Could not read the key from {address} (HTTP {status}).")
        return 2
    key = body["key"]
    report = Report()
    with tempfile.TemporaryDirectory(prefix="ext_e2e_") as work:
        workdir = Path(work)
        if "1" in args.layers:
            await layer1(report, address, key, workdir)
        if "2" in args.layers:
            from layer2 import layer2  # noqa: PLC0415 (kept separate to hold each file short)
            await layer2(report, address, key, workdir, args.offline)
    print(f"Items created in Spyglass: {sorted(set(report.ids))}")
    return report.summary()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

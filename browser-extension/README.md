# Send to Spyglass (browser extension)

When you are reading something interesting, one click sends it to Spyglass. It works on pages
behind a paywall or a bot check, because your browser already has the page open and the extension
hands that page to Spyglass. Spyglass never signs in anywhere and never sends cookies, so it could
not fetch such a page by itself.

It works in Chrome, Edge, Vivaldi, Brave and other Chromium browsers. Spyglass must be running on
the same computer.

## Install it (once)

1. Open your browser's extensions page: type `chrome://extensions` in the address bar (in Vivaldi,
   `vivaldi://extensions`; in Edge, `edge://extensions`; in Brave, `brave://extensions`) and press Enter.
2. Switch on **Developer mode** (a switch at the top right, or in the left column in Vivaldi).
3. Press **Load unpacked**.
4. Choose the folder named `browser-extension`. It sits inside the Spyglass folder. Choose the folder
   itself, not a file in it.
5. Pin the button: click the puzzle-piece icon in the toolbar and click the pin next to
   "Send to Spyglass". (If you do not pin it, the button is still in the puzzle-piece menu, where
   the browser may list it as "Access requested"; clicking it there works the same way.)
6. The extension's settings page opens by itself. In Spyglass, open **Settings**, find
   **Browser extension**, press **Show** and then **Copy** next to the key.
7. Paste the key into the **Key** field of the extension's settings page and press
   **Test connection**. It says "Connected to Spyglass" when it works. Leave the address as it is
   unless Spyglass runs on another port.

To open the settings again later: right-click the extension's button and choose Options.

## Use it

- Click the button on any page, then **Send this page**. A note ("Why this matters, or which
  project it is for") is optional and is saved with the item.
- To send only part of a page, select the text first, click the button and choose
  **Send selected text**. If the page has already been added in full, the selection is kept as a
  separate item and never replaces the full article.
- Right-click anywhere on a page and choose **Send this page to Spyglass**, or select text,
  right-click and choose **Send selected text to Spyglass**. A small desktop notification tells you
  the result.
- The keyboard shortcut **Alt+Shift+S** sends the page. You can change it on the extensions page
  (`chrome://extensions/shortcuts`).
- After sending, **Open in Spyglass** opens the item.

Pages the browser keeps to itself cannot be read: browser pages such as `chrome://` and the browser's
built-in PDF viewer (also when the address does not end in `.pdf`, as with `arxiv.org/pdf/...`). The
extension says so. For a PDF, download the file and add it in Spyglass.

## What it sends, and what it never does

It sends, only when you click or press the shortcut: the page's address, its title, the page's
HTML (or the selected text) and your note. It sends them only to Spyglass on this computer: the
address must be `http://localhost:<port>` or `http://127.0.0.1:<port>`, and the extension is not
allowed to contact any other address.

It never reads a page on its own, never watches what you browse, and never collects cookies,
passwords, history, bookmarks or anything from other tabs. It has no analytics and loads no code
from the internet. Spyglass keeps only the article text of what you send, not the rest of the page.
A very large page is cut to its article section or to its first part (the limit is
6 MB), and at most 30 pages can be sent in ten minutes.

The key lives in the browser's extension storage on this computer. If you press **Make a new
button** in Spyglass settings, the old key stops working and the extension says the key is wrong
until you paste the new one.

## Remove it

Open the extensions page, find **Send to Spyglass** and press **Remove**. Nothing else is left on
your computer. Pages already sent stay in Spyglass.

## For developers

The extension has no build step and no dependencies. `lib.js` holds the logic that can be tested
without a browser (address checks, size rules, the request, the sentences shown); it is imported by
the extension and by the interface's tests (`frontend/src/radar/extension/lib.test.ts`). The package
checks run with `node --test browser-extension/tests/*.test.js`. The icons are written by
`tools/make_icons.py`, and the result is committed.

`tests/e2e/run_e2e.py` loads the extension in a real Chromium (the one patchright installed, with a
throwaway profile) and checks installing, connecting and every way of sending against a running
Spyglass; the header of that file says how to run it. Spyglass accepts at most 30 pages in ten
minutes and a full run sends about 15, so wait ten minutes between runs. One real toolbar click
cannot be automated by it: `tests/e2e/launch_for_click.py` opens the shipped extension for that.

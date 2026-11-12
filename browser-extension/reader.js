// reader.js - the two small functions that run INSIDE the page the reader is looking at.
// They are handed to chrome.scripting.executeScript, which copies each one into the page, so
// each must be self-contained (it cannot use anything else from this file or from lib.js).
// They run only after the reader's click, and they read only what is listed here: the address,
// the title, the page's HTML and the selected text. No cookies, no storage, no history.

/**
 * Read the page (or only the selection).
 * @param {'page' | 'selection'} want what the reader asked to send
 * @param {number} articleThreshold above this many characters the <article> and <main> parts are
 *   returned too, so the caller can send just the article when the whole page is too big
 * @returns {{href: string, title: string, contentType: string, full: string, article: string | null, main: string | null,
 *   selectionText: string, selectionHtml: string}}
 */
export function collectInPage(want, articleThreshold) {
  const result = {
    href: location.href,
    title: document.title || '',
    contentType: document.contentType || '',
    full: '',
    article: null,
    main: null,
    selectionText: '',
    selectionHtml: '',
  }
  if (want === 'page') {
    result.full = document.documentElement ? document.documentElement.outerHTML : ''
    if (result.full.length > articleThreshold) {
      const article = document.querySelector('article')
      const main = document.querySelector('main')
      result.article = article ? article.outerHTML : null
      result.main = main ? main.outerHTML : null
    }
    return result
  }
  const selection = window.getSelection()
  if (selection && selection.rangeCount > 0 && !selection.isCollapsed) {
    result.selectionText = selection.toString()
    // The selection's HTML comes from copies of the selected ranges, so the page is not changed.
    const holder = document.createElement('div')
    for (let index = 0; index < selection.rangeCount; index += 1) {
      holder.appendChild(selection.getRangeAt(index).cloneContents())
    }
    result.selectionHtml = holder.innerHTML
  }
  return result
}

/**
 * Whether any text is selected on the page (the popup enables "Send selected text" from this).
 * @returns {boolean}
 */
export function hasSelectionInPage() {
  const selection = window.getSelection()
  return Boolean(selection && !selection.isCollapsed && selection.toString().trim())
}

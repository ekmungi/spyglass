// enhanceProse: in-place improvements to the reader's sanitized HTML (table wrappers, link targets, lazy images).

/** Post-process injected HTML in place: table wrappers, link targets, lazy images. */
export function enhanceProse(root: HTMLElement): void {
  root.querySelectorAll('table').forEach((table) => {
    if (table.parentElement?.classList.contains('r-table-wrap')) return
    const wrap = document.createElement('div')
    wrap.className = 'r-table-wrap'
    wrap.setAttribute('tabindex', '0')
    wrap.setAttribute('role', 'region')
    wrap.setAttribute('aria-label', 'Table (scrolls sideways)')
    table.replaceWith(wrap)
    wrap.appendChild(table)
  })
  root.querySelectorAll<HTMLAnchorElement>('a[href]').forEach((link) => {
    const href = (link.getAttribute('href') ?? '').trim()
    if (/^https?:/i.test(href)) {
      link.target = '_blank'
      link.rel = 'noopener noreferrer'
    } else if (!/^(#|mailto:)/i.test(href)) {
      // Defence in depth on top of the server's sanitiser: drop any other scheme (javascript:, data:).
      link.removeAttribute('href')
    }
  })
  root.querySelectorAll<HTMLImageElement>('img').forEach((image) => {
    image.loading = 'lazy'
    image.decoding = 'async'
  })
}

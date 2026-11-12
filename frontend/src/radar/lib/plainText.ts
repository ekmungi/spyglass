// plainText: titles and headlines are text. Feeds sometimes deliver them with HTML entities
// ("Q&amp;A") or stray markup (an <a> element wrapped around the title); this turns such a value
// into the plain words, which are then rendered as a React text node and never as markup.

/** Named entities worth decoding when no DOM parser is available (the DOM path handles all of them). */
const BASIC_ENTITIES: Record<string, string> = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ' }

/** Fallback for environments without DOMParser: strip tags, decode the common entities. */
function stripWithoutDom(value: string): string {
  return value
    .replace(/<[^>]*>/g, '')
    .replace(/&(#x?[0-9a-f]+|[a-z]+);/gi, (match, body: string) => {
      if (body[0] === '#') {
        const code = body[1] === 'x' || body[1] === 'X' ? parseInt(body.slice(2), 16) : parseInt(body.slice(1), 10)
        return Number.isFinite(code) && code > 0 && code <= 0x10ffff ? String.fromCodePoint(code) : match
      }
      return BASIC_ENTITIES[body.toLowerCase()] ?? match
    })
}

/**
 * Reduce a title-like value to plain text: tags removed (their inner text kept), entities decoded,
 * whitespace collapsed. The value is parsed in an inert document, so nothing in it runs or loads.
 */
export function plainText(value: string | null | undefined): string {
  if (!value) return ''
  // Fast path: nothing that could be markup or an entity.
  if (!/[<&]/.test(value)) return value.replace(/\s+/g, ' ').trim()
  let text: string
  if (typeof DOMParser !== 'undefined') {
    text = new DOMParser().parseFromString(value, 'text/html').body.textContent ?? ''
  } else {
    text = stripWithoutDom(value)
  }
  return text.replace(/\s+/g, ' ').trim()
}

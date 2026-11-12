// answerMarkdown: how an assistant answer is rendered. The answer is text produced by a model that
// has read untrusted pages, so it may carry instructions planted in an article. Two things follow:
// an image is never fetched (its address could carry the reader's data to another server, so only
// the alt text and the address are shown as plain text), and a link opens only if it is a plain
// web address. Raw HTML in the answer is never rendered.
import type { ComponentProps } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { openItem } from '../components/openItem'
import { safeHttpUrl } from '../lib/safeUrl'
import { remarkCitations } from './citations'

/** An image in an answer, shown as text: the alt text, then its address (never loaded). */
function ImageAsText({ alt, src }: ComponentProps<'img'>) {
  const address = typeof src === 'string' ? src : ''
  return (
    <span className="r-md__image">
      {alt ? `[image: ${alt}]` : '[image]'}
      {address && <> ({address})</>}
    </span>
  )
}

/**
 * A link that opens in a new tab if it is an http(s) address; otherwise only its text is shown.
 * A citation marker the citation pass tagged (`data-cite`, which text written by a model cannot
 * carry) is the one exception: it opens that item in the reader.
 */
function SafeLink(props: ComponentProps<'a'> & { 'data-cite'?: string }) {
  const { href, children } = props
  const cited = Number(props['data-cite'])
  if (Number.isInteger(cited) && cited > 0 && href === `#/item/${cited}`) {
    return (
      <a
        className="r-cite"
        href={href}
        title={typeof children === 'string' ? children : undefined}
        onClick={(event) => {
          event.preventDefault()
          openItem(cited)
        }}
      >
        {children}
      </a>
    )
  }
  const safe = safeHttpUrl(href)
  if (!safe) return <span>{children}</span>
  return (
    <a href={safe} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  )
}

/**
 * Render an answer's markdown with images shown as text, safe links and no raw HTML. Given
 * `citeLabel`, each `[#123]` marker becomes a small link to that item, named by the headline when
 * `citeLabel` knows it.
 */
export function AnswerMarkdown({ children, citeLabel }: { children: string; citeLabel?: (id: number) => string | null }) {
  return (
    <ReactMarkdown
      remarkPlugins={citeLabel ? [remarkGfm, [remarkCitations, { label: citeLabel }]] : [remarkGfm]}
      skipHtml
      // Addresses are vetted where they are used (SafeLink); an image address is only displayed.
      urlTransform={(url) => url}
      components={{ img: ImageAsText, a: SafeLink }}
    >
      {children}
    </ReactMarkdown>
  )
}

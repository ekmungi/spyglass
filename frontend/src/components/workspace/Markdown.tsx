// Shared Markdown renderer: wraps react-markdown + remark-gfm in the reader-markdown
// styles so the summary panel and the article body render rich text identically.
import type { ComponentPropsWithoutRef, CSSProperties } from 'react'
import ReactMarkdown, {
  defaultUrlTransform,
  type Components,
  type Options,
} from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface MarkdownProps {
  // The markdown source to render.
  children: string
  // Extra classes appended to the reader-markdown wrapper (e.g. text-body).
  className?: string
  // Inline styles for the wrapper (e.g. font size / line height).
  style?: CSSProperties
  // Optional custom element renderers (e.g. clickable highlight <mark>s; body-only).
  components?: Components
  // Optional rehype plugins (e.g. highlight-mark injection; body-only).
  rehypePlugins?: Options['rehypePlugins']
  // Enables the card:<id> link scheme: such hrefs survive sanitization
  // and clicks route to this handler instead of navigating.
  onCardLink?: (id: number) => void
}

// The anchor props we rebuild explicitly (react-markdown also passes a non-DOM
// `node` prop, so we pick fields instead of spreading).
type AnchorProps = ComponentPropsWithoutRef<'a'>

/** Build an anchor renderer that intercepts card:<id> clicks; other links are untouched. */
function cardAnchor(onCardLink: (id: number) => void) {
  return function CardAnchor({ href, title, children }: AnchorProps) {
    if (href?.startsWith('card:')) {
      return (
        <a
          href={href}
          title={title}
          onClick={(event) => {
            // Route to the in-app reader instead of navigating the webview. A
            // malformed id (card:abc) is a no-op rather than an NaN request.
            event.preventDefault()
            const id = Number(href.slice('card:'.length))
            if (Number.isFinite(id)) {
              onCardLink(id)
            }
          }}
        >
          {children}
        </a>
      )
    }
    return (
      <a href={href} title={title}>
        {children}
      </a>
    )
  }
}

/** Render markdown as rich text inside the shared `.reader-markdown` styles.
 * remark-gfm adds tables/strikethrough/autolinks; raw HTML is NOT enabled
 * (react-markdown's safe default), so rendered content can't inject arbitrary markup.
 * With onCardLink set, card:<id> hrefs survive the URL sanitizer and clicks route
 * to the handler; every other scheme keeps the default safe-protocol handling. */
export function Markdown({
  children,
  className,
  style,
  components,
  rehypePlugins,
  onCardLink,
}: MarkdownProps) {
  // Only widen the allowed protocols when a card-link handler exists.
  const urlTransform = onCardLink
    ? (url: string) => (url.startsWith('card:') ? url : defaultUrlTransform(url))
    : undefined
  const merged: Components | undefined = onCardLink
    ? { a: cardAnchor(onCardLink), ...components }
    : components
  return (
    <div className={`reader-markdown${className ? ` ${className}` : ''}`} style={style}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={rehypePlugins}
        components={merged}
        urlTransform={urlTransform}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}

// Sample-mode assistant answers (markdown), chosen by preset action, plus the SSE body that
// streams them in small chunks so the real stream parser runs in sample mode too.
import type { AssistAction, RetrievedItem } from '../api/types'

const ANSWERS: Record<AssistAction | 'question', string> = {
  explain: `In plain terms: **the model can now read a whole long document at once**, instead of in pieces.

Before this release, a long file had to be split into chunks. Each chunk was read separately, so the model could miss links between, say, a table on page 4 and a footnote on page 40.

What changes for you:

- **Cost.** Long inputs are about 60 percent cheaper, so a full clinical record costs cents rather than dollars.
- **Accuracy.** Fewer chunking errors, especially for tables and cross-references.
- **Caveat.** The benchmark numbers are the company's own; treat them as a claim until someone replicates them.`,
  relevance: `This touches three things you work on:

1. **Report drafting.** A common pipeline splits long reports into sections; a single pass could remove the stitching step.
2. **Regulatory files.** Reviewing a full technical file in one request becomes affordable, though you would still need a human check.
3. **Vendor choice.** If on-premise deployment matters, the open-weight document model in the comparison table is the one to test.

One thing to verify before acting: whether the document mode keeps page references reliably on scanned PDFs.`,
  colleagues: `Hi all, a quick note on something from today's reading.

Aster AI released a new model that reads documents of up to a million tokens in one go, and cut prices for long inputs by about 60 percent. For us, that could make full-report summarisation cheap enough to prototype properly.

The numbers are the vendor's own, so I suggest a small test on five anonymised reports before we draw conclusions. Happy to set it up if useful.`,
  linkedin: `Long documents just got cheaper to read for AI models.

A new release this week processes up to a million tokens in one pass and cuts the price of long inputs by about 60 percent.

Why it matters in medtech: clinical records and technical files are long, and splitting them into chunks is where errors creep in.

Two cautions:
- The benchmarks are the vendor's own.
- Cheaper reading does not remove the need for expert review.

Curious whether others are testing single-pass document review yet.`,
  blog: `## Working title: What a million-token context means for medical documents

### 1. The problem with chunking
- Why long records were split, and what got lost

### 2. What changed this week
- The release in two sentences
- The price change, in concrete numbers

### 3. Where it helps
- Report drafting
- Regulatory file review

### 4. Where it does not
- Scanned documents and handwriting
- Accountability: who checks the output

### 5. A small experiment you can run
- Five anonymised reports, two methods, one comparison table`,
  projects: `Two of your projects could use this, and one only loosely:

1. **Imaging AI.** The long-document mode could review a whole procedure report in one pass, which would replace a stitching step in a document pipeline. Worth exploring.
2. **Regulation notes.** Reviewing a long regulatory document in one request becomes affordable. Useful as a resource, though a human check stays necessary.
3. **Agent harness.** Only loosely related; the release says little about tool use.

Nothing has been filed. If one of these sounds right, use File this item in vault below; it joins your filing queue and is filed in one go, after your yes.`,
  feed_week: 'Nothing in your feed was ready to rank this week.',
  feed_themes: 'No themes could be found in your feed this week.',
  question: `Good question. Based on the article:

- The passage refers to the **flat-rate pricing** for inputs above 200,000 tokens.
- The company says this reflects how customers use the model: mostly long documents rather than chat.

The article does not say how the price compares with self-hosting an open-weight model, so that part remains open.`,
}

/** Pick the sample answer for an action (or a free question). */
export function answerFor(action: AssistAction | null | undefined, content: string): string {
  if (action && action in ANSWERS) return ANSWERS[action]
  if (/brief|today/i.test(content)) {
    return `Today's brief in three lines:\n\n- **Models:** long documents became cheap to process in one pass.\n- **Companies:** one imaging company won a clearance; another raised a growth round.\n- **Worth a read:** the surgical-video benchmark in Papers is the item most worth a close read.`
  }
  return ANSWERS.question
}

/** Split text into small chunks (a few words each) to imitate token streaming. */
export function chunkText(text: string): string[] {
  const parts = text.match(/\S+\s*/g) ?? [text]
  const chunks: string[] = []
  for (let i = 0; i < parts.length; i += 3) chunks.push(parts.slice(i, i + 3).join(''))
  return chunks
}

/**
 * A ReadableStream that emits the answer as SSE `data:` lines. Lines are deliberately split
 * across chunk boundaries to exercise the parser. Stops early when the signal aborts.
 */
export function sseStream(text: string, messageId: number, signal?: AbortSignal | null, failWith?: string, retrieved?: RetrievedItem[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  const events = failWith
    ? [...chunkText(text.slice(0, 120)).map((t) => ({ type: 'delta', text: t })), { type: 'error', message: failWith }]
    : [...chunkText(text).map((t) => ({ type: 'delta', text: t })), { type: 'done', message_id: messageId, ...(retrieved ? { retrieved } : {}) }]
  // Keep-alive comment lines (": ping") appear as the real server sends them; the parser skips them.
  const payload = ': ping\n\n' + events.map((event, index) => `${index === 6 ? ': ping\n\n' : ''}data: ${JSON.stringify(event)}\n\n`).join('')
  let offset = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  return new ReadableStream<Uint8Array>({
    start(controller) {
      const pump = () => {
        if (signal?.aborted) {
          controller.error(new DOMException('Aborted', 'AbortError'))
          return
        }
        if (offset >= payload.length) {
          controller.close()
          return
        }
        // Emit 40-90 characters at a time, ignoring line boundaries.
        const size = 40 + Math.floor(Math.random() * 50)
        controller.enqueue(encoder.encode(payload.slice(offset, offset + size)))
        offset += size
        timer = setTimeout(pump, 45)
      }
      timer = setTimeout(pump, 600)
    },
    cancel() {
      if (timer) clearTimeout(timer)
    },
  })
}

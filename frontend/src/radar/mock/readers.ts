// Sample-mode reader documents: an article with images and a table, a paper with math, a video
// with a transcript, a PDF notice, and a generic article for every other item.
import type { RadarItem, ReaderDoc } from '../api/types'
import { CHART_IMAGE, DIAGRAM_IMAGE, VIDEO_POSTER_HTML } from './images'

const ARTICLE_HTML = `
<p>Aster AI released Aster 4 on Tuesday, its first model with a context window of one million tokens in the standard tier. The company also cut prices for long inputs by roughly 60 percent, saying that most of its enterprise traffic is now document analysis rather than chat.</p>
<p>The release matters less for the headline context length than for what it costs to use. Until now, processing a full clinical record or a long regulatory file in one pass was possible but expensive; teams split documents into chunks and accepted the errors that chunking introduces.</p>
<h2>What changed</h2>
<p>Three things are new in this release:</p>
<ul>
<li>A standard tier that accepts up to one million tokens per request.</li>
<li>Lower prices for inputs above 200,000 tokens, billed at a flat rate.</li>
<li>A <em>document mode</em> that keeps page numbers and table structure in its answers.</li>
</ul>
<figure><img src="${CHART_IMAGE}" alt="Line chart: the new model's accuracy rises from 60 to 88 percent over eight releases, ahead of the previous model and the baseline." /><figcaption>Accuracy on a long-document question-answering benchmark across releases. Source: the company's technical report.</figcaption></figure>
<h2>How it compares</h2>
<p>The company published results on three long-document benchmarks. Independent replication has not yet been reported, and the comparison uses the providers' own published numbers.</p>
<table>
<thead><tr><th>Model</th><th>Context</th><th>Long-document QA</th><th>Table extraction</th><th>Price per million input tokens</th></tr></thead>
<tbody>
<tr><td>Aster 4</td><td>1,000,000</td><td>88.1%</td><td>91.4%</td><td>$1.20</td></tr>
<tr><td>Aster 3.5</td><td>400,000</td><td>81.7%</td><td>86.0%</td><td>$3.00</td></tr>
<tr><td>Corvid Docs (open weights)</td><td>256,000</td><td>79.2%</td><td>89.9%</td><td>self-hosted</td></tr>
</tbody>
</table>
<blockquote><p>"Most of what our customers send us is not a conversation. It is a stack of documents and a question about them."</p></blockquote>
<h3>For developers</h3>
<p>The new mode is enabled with a single request flag. Existing integrations keep working unchanged.</p>
<pre><code>client.messages.create(
    model="aster-4",
    document_mode=True,
    input=[report_pdf, "List every adverse event with its page number."],
)</code></pre>
<p>Pricing for the new tier applies from the first of next month. Aster AI said the older 3.5 models will remain available for at least a year.</p>
`

const PAPER_HTML = `
<p><strong>Abstract.</strong> We benchmark seven self-supervised pretraining recipes on surgical and endoscopic video across seven downstream tasks, including phase recognition, tool detection and lesion localisation. Masked video modelling outperforms contrastive pretraining on six of the seven tasks, and the gap widens when labelled data is scarce.</p>
<h2>1. Introduction</h2>
<p>Annotated surgical video is expensive: one hour of footage can take a specialist several hours to label. Self-supervised pretraining promises to learn useful representations from unlabelled video, but published comparisons use different datasets, backbones and evaluation protocols.</p>
<h2>2. Method</h2>
<p>For a clip with frames <math><msub><mi>x</mi><mn>1</mn></msub><mo>,</mo><mo>…</mo><mo>,</mo><msub><mi>x</mi><mi>T</mi></msub></math>, masked video modelling hides a random subset <math><mi>M</mi></math> of spatio-temporal patches and trains the encoder to reconstruct them. The loss is the mean squared error over the masked patches:</p>
<math display="block"><mrow><mi mathvariant="script">L</mi><mo>=</mo><mfrac><mn>1</mn><mrow><mo>|</mo><mi>M</mi><mo>|</mo></mrow></mfrac><munder><mo>∑</mo><mrow><mi>i</mi><mo>∈</mo><mi>M</mi></mrow></munder><msup><mrow><mo>‖</mo><msub><mover><mi>x</mi><mo>^</mo></mover><mi>i</mi></msub><mo>−</mo><msub><mi>x</mi><mi>i</mi></msub><mo>‖</mo></mrow><mn>2</mn></msup></mrow></math>
<p>We use a masking ratio of <math><mi>ρ</mi><mo>=</mo><mn>0.9</mn></math>, which we found more effective on video than the 0.75 common for still images, because neighbouring frames are highly redundant.</p>
<figure><img src="${DIAGRAM_IMAGE}" alt="Block diagram of the evaluation pipeline: video frames, detection, clinician review, report." /><figcaption>Figure 2. Evaluation pipeline for the lesion-localisation task.</figcaption></figure>
<h2>3. Results</h2>
<table>
<thead><tr><th>Pretraining</th><th>Phase F1</th><th>Tool mAP</th><th>Lesion AP</th><th>Tasks won</th></tr></thead>
<tbody>
<tr><td>Masked video modelling</td><td>0.871</td><td>0.792</td><td>0.684</td><td>6 / 7</td></tr>
<tr><td>Contrastive (clip-level)</td><td>0.842</td><td>0.771</td><td>0.641</td><td>1 / 7</td></tr>
<tr><td>Supervised (ImageNet)</td><td>0.803</td><td>0.744</td><td>0.602</td><td>0 / 7</td></tr>
</tbody>
</table>
<p>With 10 percent of the labels, masked pretraining retains 94 percent of its full-label performance, against 86 percent for contrastive pretraining.</p>
<h2>4. Limitations</h2>
<p>All datasets come from a small number of centres, and none includes paediatric procedures. Results on lesion localisation use a single annotator per video.</p>
`

const VIDEO_HTML = `
<h2>Transcript</h2>
<p><strong>00:00</strong> Thanks for having me. I want to talk about what happens after a learning system is cleared, because that is where most of our engineering time actually goes.</p>
<p><strong>02:14</strong> Every update starts with a change request that says which component changes, why, and which tests prove it still works. We keep a fixed validation set that no one is allowed to train on.</p>
<p><strong>06:40</strong> The hard part is deciding what counts as a significant change. Our rule of thumb: if the intended use, the input data or the performance claims move, it is significant, and it goes back to the regulator.</p>
<p><strong>11:05</strong> We monitor field performance weekly. When the detection rate drifts outside its band, the system flags it before any clinician would notice.</p>
<p><strong>17:30</strong> If I had to give one piece of advice: write the change-control plan before the first submission, not after.</p>
`

const PDF_NOTICE_HTML = `
<p><strong>Abstract.</strong> We study how the performance of multimodal medical foundation models scales with paired image-and-text data, model size and compute. Gains follow a power law up to roughly 50 million pairs, after which data quality matters more than quantity.</p>
<p>This paper is shown as its original PDF because its layout could not be converted to clean text.</p>
`

/** Build a plain sample article for items without a hand-written document. */
function genericHtml(item: RadarItem): string {
  return `
<p>${item.why ?? 'This is a sample article used in sample mode.'}</p>
<p>The full text of the source appears here, cleaned of navigation, advertising and cookie banners, with its own headings, lists, tables and images kept. This sample paragraph stands in for that text.</p>
<h2>Background</h2>
<p>Reports like this one usually include the announcement itself, a few lines of context from people involved, and the open questions that remain. The reader keeps the original structure so that you can scan headings first and read closely where it matters.</p>
<h2>What to watch</h2>
<ul><li>Whether independent groups replicate the numbers.</li><li>How quickly other companies respond.</li><li>What regulators or customers say in the coming weeks.</li></ul>
<p>Use <em>Open original</em> above to read the article on its own site.</p>
`
}

const WORDS = (html: string) => html.replace(/<[^>]+>/g, ' ').split(/\s+/).filter(Boolean).length

/** The reader document for one sample item (status 'ok'); special kinds for a few known ids. */
export function readerFor(item: RadarItem): ReaderDoc {
  const base: ReaderDoc = {
    kind: 'article',
    html: genericHtml(item),
    title: item.headline,
    byline: null,
    site: item.origin,
    lead_image: null,
    word_count: 0,
    source_url: item.url,
    alt_url: null,
    status: 'ok',
    error: null,
  }
  let doc: ReaderDoc = base
  if (item.id === 101) doc = { ...base, html: ARTICLE_HTML, byline: 'By Dana Reyes' }
  else if (item.kind === 'paper' && item.id === 116) doc = { ...base, kind: 'pdf', html: PDF_NOTICE_HTML, alt_url: `${item.url}.pdf` }
  else if (item.kind === 'paper') doc = { ...base, kind: 'paper', html: item.id === 113 ? PAPER_HTML : genericHtml(item), byline: 'A. Moreau, K. Osei, L. Brandt', alt_url: `${item.url}.pdf` }
  else if (item.kind === 'video') doc = { ...base, kind: 'video', html: VIDEO_HTML, alt_url: VIDEO_POSTER_HTML }
  else if (item.state.from_user && item.state.captured_via === 'slack') doc = { ...base, kind: 'note' }
  // Word count drives the "N min read" label; the generic article is padded to a realistic length.
  const words = WORDS(doc.html)
  return { ...doc, word_count: doc.html === base.html ? words * 6 : words * 2 }
}

/** Key points shown in the summary block; generic points for items without their own. */
export function keyPointsFor(item: RadarItem): string[] {
  if (item.id === 101) {
    return [
      'Aster 4 accepts up to one million tokens per request in the standard tier.',
      'Prices for long inputs fall by about 60 percent from next month.',
      'A new document mode keeps page numbers and table structure in answers.',
      'Benchmark numbers are the company’s own; no independent replication yet.',
    ]
  }
  if (item.id === 113) {
    return [
      'Masked video modelling beats contrastive pretraining on six of seven surgical-video tasks.',
      'A masking ratio of 0.9 works better on video than the 0.75 used for images.',
      'With 10 percent of labels it keeps 94 percent of full-label performance.',
    ]
  }
  return [
    'The main announcement and who made it.',
    'The numbers or evidence offered in support.',
    'What remains unconfirmed or open.',
  ]
}

// Sample-mode feed: 40 invented items across every section, kind and tier. All company and
// publication names are fictional; the content is generic sample text.
import type { ItemKind, RadarItem, Tier } from '../api/types'

export const SECTION_LABELS: Record<string, string> = {
  models: 'Models & platforms',
  labs: 'Labs & research',
  agents: 'Building with agents',
  health: 'Healthcare AI & medtech',
  industry: 'Industry & use cases',
  direction: 'Where AI is heading',
}

type Row = [
  headline: string,
  origin: string,
  section: string,
  kind: ItemKind,
  tier: Tier,
  score: number,
  why: string,
  hoursAgo: number,
  signal?: string,
  capturedVia?: string,
]

// One row per item; ids are assigned in order starting at 101.
const ROWS: Row[] = [
  ['Aster AI releases Aster 4 with a million-token context and lower prices', 'Signal Ledger', 'models', 'release', 'top', 94,
    'The new tier makes long clinical documents cheap to process in one pass, which changes the cost case for report-drafting tools.', 5, '612 points on Hacker News'],
  ['Endovista wins clearance for a real-time polyp-detection update', 'Medtech Dispatch', 'health', 'regulatory', 'top', 92,
    'A new result in a field you follow: an imaging company reports a cleared second-generation detector with a lower false-alarm rate.', 7],
  ['Kestrel open-sources its agent harness with built-in tool permissions', 'The Agent Notebook', 'agents', 'tool', 'top', 88,
    'A permission model you can copy for your own agent setup, with tests and a small plugin format.', 9, '388 points on Hacker News'],
  ['Hospitals report what changed after a year of ambient note-taking', 'Clinical AI Review', 'health', 'research', 'top', 86,
    'The first multi-site numbers on clinician time saved, with an honest section on where adoption stalled.', 11],
  ['Lumen Labs publishes a method for checking model reasoning step by step', 'Frontier Notes', 'labs', 'research', 'notable', 81,
    'A practical evaluation idea you could adapt for checking how a model explains a detection.', 13],
  ['Halcyon Surgical shows a supervised autonomous suturing trial', 'Medtech Dispatch', 'health', 'news', 'notable', 80,
    'A new result in a field you follow: the trial design is a template for how regulators may view supervised autonomy.', 14],
  ['Corvid Systems ships an open-weight vision model tuned for documents', 'Open Weights Weekly', 'models', 'release', 'notable', 78,
    'Strong on scanned forms and tables; a candidate for on-premise pipelines where data cannot leave the hospital.', 16, '214 points on Hacker News'],
  ['A field guide to memory for long-running coding agents', 'The Agent Notebook', 'agents', 'post', 'notable', 77,
    'Concrete patterns for what to keep, summarise and forget between sessions, with trade-offs measured.', 18],
  ['Orrin Therapeutics credits AI design for a faster preclinical candidate', 'Industry Brief Daily', 'industry', 'news', 'notable', 74,
    'A rare case with timelines and costs disclosed, useful when colleagues ask whether AI moves real milestones.', 20],
  ['Why compute costs may fall slower than the market expects', 'Policy & Compute', 'direction', 'opinion', 'notable', 72,
    'A well-argued counterpoint to the price-cut narrative, relevant to multi-year product cost plans.', 22],
  ['Northgate Logistics cuts stock-outs with an agent that reorders supplies', 'Industry Brief Daily', 'industry', 'news', 'notable', 70,
    'An operations use case with numbers that maps neatly onto hospital supply rooms.', 23],
  ['Meridian Imaging opens a dataset of annotated colonoscopy video', 'Clinical AI Review', 'health', 'news', 'notable', 76,
    'Public, consented and annotated by specialists; worth checking its licence for benchmarking.', 25],
  ['Self-supervised pretraining for surgical video: a benchmark across seven tasks', 'arXiv', 'health', 'paper', 'top', 87,
    'Relevant to your interest in medical imaging AI: compares pretraining recipes on procedure video, with code released.', 6, '96 community upvotes'],
  ['Calibrated uncertainty for detection models in clinical deployment', 'arXiv', 'health', 'paper', 'notable', 79,
    'Shows a cheap way to report when a detector is unsure, which reviewers increasingly ask for.', 15, '41 community upvotes'],
  ['Small models that plan: distilling tool use from larger agents', 'arXiv', 'agents', 'paper', 'notable', 75,
    'A recipe for running capable agents on modest hardware.', 19, '133 community upvotes'],
  ['Scaling laws for multimodal medical foundation models', 'arXiv', 'labs', 'paper', 'notable', 73,
    'Evidence on how much paired image-and-text data medical models need before gains flatten.', 26, '58 community upvotes'],
  ['Lucent Scope raises a growth round for AI-guided endoscopes', 'Medtech Dispatch', 'health', 'news', 'top', 90,
    'A company in a field you follow raised fresh capital; it plans a European launch next year.', 8],
  ['Tessellate adds a hosted directory of MCP servers', 'The Agent Notebook', 'agents', 'tool', 'skim', 58,
    'A searchable catalogue of tool servers.', 10],
  ['Aster AI updates its usage policy for medical advice', 'Signal Ledger', 'models', 'news', 'skim', 61,
    'Clarifies what clinical uses the terms allow.', 12],
  ['Video: how a surgical robotics team validates software updates', 'Surgical Systems Talks', 'health', 'video', 'notable', 71,
    'A 20-minute walkthrough of a change-control process for learning systems.', 17],
  ['Brightline Health pilots AI triage in three emergency departments', 'Clinical AI Review', 'health', 'news', 'skim', 60,
    'Early pilot, no outcomes yet.', 21],
  ['A practical checklist for evaluating LLM features before launch', 'Frontier Notes', 'direction', 'post', 'skim', 57,
    'Short and usable.', 24],
  ['Open benchmark for agent reliability on long tasks', 'Open Weights Weekly', 'agents', 'research', 'skim', 59,
    'Measures how often agents finish multi-hour tasks.', 27],
  ['Lumen Labs hires a former hospital CIO to lead health partnerships', 'Signal Ledger', 'labs', 'news', 'skim', 55,
    'A signal of where the lab sees its next market.', 28],
  ['Edge chips for medical devices get a new low-power option', 'Medtech Dispatch', 'industry', 'news', 'skim', 56,
    'Relevant if detection must run inside the device.', 29],
  ['Corvid Systems explains its training data filtering', 'Open Weights Weekly', 'models', 'post', 'skim', 54,
    'Useful context for data provenance questions.', 30],
  ['The quiet consolidation of AI coding tools', 'Policy & Compute', 'direction', 'opinion', 'skim', 53,
    'Three acquisitions in a month, and what they suggest.', 31],
  ['Hospital procurement teams publish an AI questionnaire', 'Clinical AI Review', 'health', 'regulatory', 'skim', 62,
    'The questions buyers will now ask every vendor.', 32],
  ['Kestrel adds voice control to its terminal agent', 'The Agent Notebook', 'agents', 'release', 'skim', 52,
    'A small release.', 33],
  ['How a retailer uses agents to answer supplier email', 'Industry Brief Daily', 'industry', 'post', 'skim', 51,
    'A tidy case study.', 34],
  ['Notes from a talk on post-market surveillance for AI devices', 'Medtech Dispatch', 'health', 'post', 'notable', 69,
    'You shared this; it outlines monitoring duties that apply to AI-enabled devices.', 4, undefined, 'slack'],
  ['Thread: lessons from shipping an internal agent to 400 staff', 'The Agent Notebook', 'agents', 'post', 'notable', 68,
    'You saved this; it covers rollout, permissions and the support load in the first month.', 3, undefined, 'raindrop'],
  ['Weekend reading: a long interview on the economics of inference', 'Policy & Compute', 'direction', 'opinion', 'skim', 50,
    'Long, but the section on pricing power is worth it.', 36],
  ['Ten gadgets for your desk this winter', 'Gadget Roundup', '', 'news', 'out', 8,
    'Consumer gadget deals; outside your interests.', 6],
  ['Celebrity chef launches an AI recipe app', 'Lifestyle Daily', '', 'news', 'out', 6,
    'Lifestyle news; outside your interests.', 9],
  ['The best puzzle games of the year', 'Play Weekly', '', 'opinion', 'out', 4,
    'Games; outside your interests.', 12],
  ['Fantasy league tips powered by a chatbot', 'Sports Desk', '', 'news', 'out', 5,
    'Sports; outside your interests.', 15],
  ['Smart speaker discounts ahead of the holidays', 'Gadget Roundup', '', 'news', 'out', 7,
    'Consumer deals; outside your interests.', 18],
  ['Video: a lab tour of a new robotics research centre', 'Frontier Notes', 'labs', 'video', 'skim', 49,
    'A short tour.', 38],
  ['Regulators propose guidance on change control for learning devices', 'Medtech Dispatch', 'health', 'regulatory', 'notable', 83,
    'Draft rules for updating cleared models without a full re-review; the comment period is open.', 26],
]

/** Build an ISO timestamp `hours` before now. */
export function hoursAgo(hours: number): string {
  return new Date(Date.now() - hours * 3600_000).toISOString()
}

/** Make a URL-safe slug from a headline, for the sample URLs. */
function slug(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60)
}

/** Build the 40 sample RadarItems (ids 101–140), newest first by row order. */
export function buildItems(): RadarItem[] {
  return ROWS.map(([headline, origin, section, kind, tier, score, why, hours, signal, capturedVia], index) => {
    const id = 101 + index
    return {
      id,
      title: headline,
      headline,
      url: `https://example.org/${slug(origin)}/${slug(headline)}`,
      source: capturedVia ? 'capture' : kind === 'paper' ? 'hf_papers' : 'rss',
      origin,
      published_at: hoursAgo(hours),
      fetched_at: hoursAgo(Math.max(0, hours - 1)),
      kind,
      section,
      section_label: SECTION_LABELS[section] ?? '',
      tier,
      score,
      why,
      key_points: [],
      entities: [],
      signal: signal ?? null,
      state: {
        saved: index === 6 || index === 13,
        opened: false,
        vote: null,
        from_user: Boolean(capturedVia),
        captured_via: capturedVia ?? null,
        vault_path: null,
      },
      has_reader: true,
    }
  })
}

// Sample-mode answers for "Open in Claude Code", the projects the assistant may mention and the
// privacy overview, so all three can be clicked through with ?mock=1 and no backend.
import type { ClaudeRequest, PrivacyOutbound, ProjectRow } from '../api/types'
import { sampleSettings } from '../pages/sources/legacyMock'
import { mockState, patchItem } from './store'

/** The notes vault named in sample previews. */
const SAMPLE_VAULT = 'C:/Notes/Vault'
/** How long after "Open" the sample Claude Code session reports where it filed the item. */
const FILED_AFTER_MS = 6000

const SEED_PROJECTS: ProjectRow[] = [
  { name: 'Imaging AI', description: 'Notes on AI methods for medical imaging.', in_vault: true },
  { name: 'Agent harness', description: '', in_vault: true },
  { name: 'Regulation notes', description: 'Reading on how AI systems are validated and regulated.', in_vault: true },
  { name: 'Old prototype', description: 'An archived idea about report drafting.', in_vault: false },
]

let projects: ProjectRow[] = SEED_PROJECTS

/** Forget the edits made to the sample project list (tests, and a fresh visit to sample mode). */
export function resetClaudeMock(): void {
  projects = SEED_PROJECTS
}

/** A JSON Response with the given status. */
function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
}

/** The text a sample preview shows for an item and a choice (mirrors what the service would send). */
function previewText(headline: string, url: string, why: string | null, request: ClaudeRequest): string {
  const item = [`Title: ${headline}`, `Link: ${url}`, why ? `Why Spyglass showed it: ${why}` : null].filter(Boolean).join('\n')
  if (request.intent === 'custom') return `${request.custom?.trim() ?? ''}\n\n${item}`.trim()
  if (request.intent === 'discuss') {
    return `I would like to discuss this item with you. Read it first, then ask me what I want to know.\n\n${item}`
  }
  const where = request.project ? `into my project "${request.project}"` : 'into the project where it fits best (tell me which one you picked)'
  const kind = request.as_kind ? `, as a note of the kind "${request.as_kind}"` : ''
  return `Please file this item ${where}${kind}. Show me what you will write and ask before you save anything.\n\n${item}`
}

/** The project the reader named in their own note, when there is one. */
function hintFrom(note: string | null | undefined): { name: string; source: 'note' } | null {
  const text = (note ?? '').toLowerCase()
  const found = projects.find((project) => project.in_vault && text.includes(project.name.toLowerCase()))
  return found ? { name: found.name, source: 'note' } : null
}

/** POST /items/{id}/claude/preview and /claude/open. */
export function claudeRoute(method: string, id: number, action: string, body: Record<string, unknown>): Response | null {
  if (method !== 'POST') return null
  const item = mockState().items.find((entry) => entry.id === id)
  if (!item) return json({ detail: 'Not found' }, 404)
  const request = body as unknown as ClaudeRequest
  if (action === 'preview') {
    return json({
      text: previewText(item.headline, item.url, item.why, request),
      vault: SAMPLE_VAULT,
      available: true,
      reason: null,
      project_hint: hintFrom(item.state.note ?? item.note),
    })
  }
  if (action === 'open') {
    if (request.intent === 'file') {
      // The reader's own session reports back later; the sample does so after a few seconds.
      setTimeout(() => {
        const project = request.project || projects.find((entry) => entry.in_vault)?.name || null
        patchItem(id, { filed: { path: `${project ?? 'Inbox'}/Resources/${item.headline.slice(0, 40)}.md`, project, at: new Date().toISOString() } })
      }, FILED_AFTER_MS)
    }
    return json({ opened: true })
  }
  return null
}

/** GET and PUT /projects. */
export function projectsRoute(method: string, body: Record<string, unknown>): Response | null {
  if (method === 'GET') return json({ projects })
  if (method !== 'PUT') return null
  const sent = (body.projects as { name: string; description: string }[] | undefined) ?? []
  const keptInVault = projects.filter((row) => row.in_vault).map((row) => ({ ...row, description: sent.find((entry) => entry.name === row.name)?.description ?? '' }))
  const strayKept = sent
    .filter((entry) => projects.some((row) => row.name === entry.name && !row.in_vault))
    .map((entry) => ({ name: entry.name, description: entry.description, in_vault: false }))
  projects = [...keptInVault, ...strayKept]
  return json({ projects })
}

/** GET /privacy/outbound: sample destinations, and the four switches as the sample settings hold them. */
export function privacyRoute(profileBlock: string, liked: string[], disliked: string[]): Response {
  const settings = sampleSettings()
  const on = (key: string) => settings[key] === true
  const body: PrivacyOutbound = {
    model_provider: { name: 'OpenRouter', host: 'openrouter.ai' },
    profile_block: profileBlock,
    example_titles: on('privacy_send_examples') ? { liked, disliked } : { liked: [], disliked: [] },
    destinations: [
      { name: 'OpenRouter', host: 'openrouter.ai', purpose: 'Judges items and answers your questions', what_is_sent: 'Your profile text and the text of the item being judged', carries_secret: true, enabled: true },
      { name: 'News sites and feeds', host: 'the sites you follow', purpose: 'Reads articles and feeds', what_is_sent: 'A plain page request with no cookies and no sign-in', carries_secret: false, enabled: true },
      { name: 'arXiv', host: 'export.arxiv.org', purpose: 'Finds papers on your topics', what_is_sent: 'Your topic words', carries_secret: false, enabled: true },
      { name: 'Outside rendering service', host: 'r.jina.ai', purpose: 'Reads pages that block Spyglass', what_is_sent: 'The address of the page you read', carries_secret: true, enabled: on('jina_enabled') },
    ],
    switches: {
      privacy_send_examples: on('privacy_send_examples'),
      privacy_proxy_images: on('privacy_proxy_images'),
      jina_enabled: on('jina_enabled'),
      privacy_allow_bot_checks: on('privacy_allow_bot_checks'),
    },
  }
  return json(body)
}

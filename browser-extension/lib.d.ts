// lib.d.ts - the types of lib.js, so the interface's TypeScript tests can import it. The extension
// itself is plain JavaScript and does not use this file.

export declare const DEFAULT_ADDRESS: string
export declare const LIMITS: {
  readonly htmlBytes: number
  readonly textBytes: number
  readonly fallbackChars: number
  readonly titleChars: number
  readonly noteChars: number
}
export declare const TIMEOUT_MS: number

export type Checked<T> = ({ ok: true } & T) | { ok: false; message: string }

export declare function normalizeAddress(input: unknown): Checked<{ address: string }>
export declare function normalizeKey(input: unknown): Checked<{ key: string }>
export declare function classifyPage(url: string | undefined): 'ok' | 'internal' | 'pdf'
export declare function siteOf(url: string | undefined): string
export declare function byteLength(text: string): number
export declare function clipToBytes(text: string, maxBytes: number): string
export declare function chooseHtml(parts: { full: string; article?: string | null; main?: string | null }): string

export interface PageRead {
  href: string
  title?: string
  contentType?: string
  full?: string
  article?: string | null
  main?: string | null
  selectionText?: string
  selectionHtml?: string
}
export declare function buildPayload(
  read: PageRead,
  kind: 'page' | 'selection',
  note?: string,
): { ok: true; payload: Record<string, any> } | { ok: false; reason: 'no-selection' | 'empty' | 'pdf' }

export type Outcome =
  | { kind: 'ok'; data: any }
  | { kind: 'no-key' }
  | { kind: 'http'; status: number; detail: string }
  | { kind: 'network' }
  | { kind: 'timeout' }

export interface CallRequest {
  address: string
  key: string
  path: string
  method: 'GET' | 'POST'
  payload?: object
  fetchImpl?: typeof fetch
  timeoutMs?: number
}
export declare function callSpyglass(request: CallRequest): Promise<Outcome>
export declare function sendToSpyglass(request: Omit<CallRequest, 'path' | 'method'> & { payload: object }): Promise<Outcome>
export declare function checkSpyglass(request: Omit<CallRequest, 'path' | 'method' | 'payload'>): Promise<Outcome>

export declare function describeOutcome(
  outcome: { kind: string; status?: number; detail?: string; data?: any },
  purpose?: 'send' | 'check',
): { ok: boolean; message: string; hint?: string }
export declare function itemUrl(address: string, itemId: number): string

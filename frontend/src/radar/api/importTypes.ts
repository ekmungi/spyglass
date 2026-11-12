// Shapes for bringing in a page the reader has open (the Send to Spyglass button and pasted text).

/* ---------- import (bring in a page the reader has open) ---------- */

/** POST /import/stage (JSON): the page the import window received from the Send to Spyglass button. */
export interface StageImportBody {
  url: string
  title: string
  html: string
  /** The origin of the page that sent it; shown to the reader, never trusted. */
  sender: string
  /** The button's secret, copied from the message; the service refuses a missing or wrong one. */
  key: string
}

/** GET /import/staged/{token}: what the confirmation window shows. */
export interface StagedImport {
  token: string
  url: string
  host: string
  title: string
  site: string
  word_count: number
  /** The first words of the article as the reader will show it, as plain text. */
  excerpt: string
  /** The host of the site that really sent the page; null when it is not known. */
  sender: string | null
  /** Whether the sender's site is the site the page says it is from. */
  sender_matches: boolean
  /** The item already stored for this address; adding replaces its reader copy. */
  existing_item_id: number | null
  /** Whether adding would replace an existing item. */
  replaces_existing: boolean
  /** Whether the service will refuse that replacement because the sender is not exactly the page's host. */
  replace_refused: boolean
}

/** GET /import/button-key and POST /import/button-key/rotate: the bookmark button's secret. */
export interface ImportButtonKey {
  key: string
}

/** POST /import/text: pasted text (plain text or copied HTML) for an address. */
export interface ImportTextBody {
  url: string
  text: string
  title?: string
}

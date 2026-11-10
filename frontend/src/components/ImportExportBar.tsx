// Import/export bar: OPML/markdown file import via file picker; OPML/Markdown export.
import { useRef, useState } from 'react'
import * as api from '../lib/api'

interface Props {
  onRefresh: () => void
}

/** Trigger a browser download of text content with the given filename. */
function downloadText(content: string, filename: string): void {
  const blob = new Blob([content], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

/** Toolbar for importing feeds from a file and exporting to OPML or Markdown. */
export function ImportExportBar({ onRefresh }: Props) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [importResult, setImportResult] = useState<{ added: number; skipped: number } | null>(null)
  const [importError, setImportError] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setImportResult(null)
    setImportError(null)
    try {
      const content = await file.text()
      const result = await api.importFeeds(content)
      setImportResult(result)
      onRefresh()
    } catch (err) {
      setImportError(err instanceof Error ? err.message : 'Import failed')
    } finally {
      // Reset file input so the same file can be re-imported if needed.
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  async function handleExport(format: 'opml' | 'markdown') {
    setExporting(true)
    try {
      const content = await api.exportFeeds(format)
      const ext = format === 'opml' ? 'opml' : 'md'
      downloadText(content, `spyglass-feeds.${ext}`)
    } finally {
      setExporting(false)
    }
  }

  return (
    <div
      className="flex flex-wrap items-center gap-3 border-t border-border pt-4"
      style={{ fontSize: 'var(--font-size-body)' }}
    >
      {/* Import */}
      <label className="flex cursor-pointer items-center gap-2 text-muted hover:text-ink">
        <span>Import</span>
        <input
          ref={fileRef}
          type="file"
          accept=".opml,.xml,.md,.txt"
          className="sr-only"
          aria-label="Import feeds file"
          onChange={handleFileChange}
        />
      </label>

      {/* Export buttons */}
      <button
        type="button"
        disabled={exporting}
        onClick={() => handleExport('opml')}
        className="text-muted hover:text-ink disabled:opacity-50"
        aria-label="Export OPML"
      >
        Export OPML
      </button>
      <button
        type="button"
        disabled={exporting}
        onClick={() => handleExport('markdown')}
        className="text-muted hover:text-ink disabled:opacity-50"
        aria-label="Export Markdown"
      >
        Export Markdown
      </button>

      {/* Import result feedback */}
      {importResult && (
        <span className="text-accent2" style={{ fontSize: 'var(--font-size-meta)' }}>
          Added {importResult.added}, skipped {importResult.skipped}
        </span>
      )}
      {importError && (
        <span className="text-accent" style={{ fontSize: 'var(--font-size-meta)' }}>
          {importError}
        </span>
      )}
    </div>
  )
}

// Settings section "Parts not installed": the optional parts Windows setup left out (PDF reading,
// the local AI model), what each one changes, and how to add it. Hidden when nothing is missing or
// when the service cannot say.
import { useEffect, useState } from 'react'
import { getCapabilities } from '../../api/client'
import type { MissingPart } from '../../api/types'
import { SectionHeading } from '../../ui'

/** The section, shown only while at least one optional part is missing. */
export function PartsSection() {
  const [missing, setMissing] = useState<MissingPart[]>([])

  useEffect(() => {
    const controller = new AbortController()
    getCapabilities(controller.signal).then(
      (found) => setMissing(found.missing),
      () => setMissing([]),
    )
    return () => controller.abort()
  }, [])

  if (missing.length === 0) return null
  return (
    <section aria-labelledby="settings-parts" className="rst-section">
      <SectionHeading id="settings-parts">Parts not installed</SectionHeading>
      {missing.map((part) => (
        <div key={part.id} className="r-field">
          <strong>{part.name}</strong>
          <span className="r-meta">{part.effect}</span>
          <span className="r-meta">{part.how_to_add}</span>
        </div>
      ))}
    </section>
  )
}

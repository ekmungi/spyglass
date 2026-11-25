// EnginesSection: the "AI engines" group: the default engine and model, then one row per engine.
import { useState } from 'react'
import { useStayListed } from '../../hooks/useStayListed'
import { Button, SectionHeading, Skeleton } from '../../ui'
import type { EngineRow, SettingsValues } from './api'
import { CustomServer } from './CustomServer'
import { DefaultEngine } from './DefaultEngine'
import { EngineItem } from './EngineItem'
import { JudgingProviders } from './JudgingProviders'

export interface EnginesSectionProps {
  engines: readonly EngineRow[] | null
  loading: boolean
  error: string | null
  onRetry: () => void
  /** Replace the list (after a change to one engine, an add or a removal). */
  onEngines: (engines: EngineRow[]) => void
  savedDefault: { engine: string; model: string }
  onDefaultSaved: (value: { engine: string; model: string }) => void
  /** The editable settings, once loaded; the judging block needs them. */
  settings?: SettingsValues | null
  onSettingsSaved?: (stored: SettingsValues) => void
}

/**
 * The engines that are not set up, when the list can fold them away: the ones to hide. A custom server
 * counts as set up whatever its status, because the reader added it on purpose and it would otherwise
 * disappear from the list the moment it was added. With none set up, or all set up, there is nothing to
 * fold away: no row is hidden and no button shows.
 */
function foldable(engines: readonly EngineRow[]): ReadonlySet<string> {
  const off = engines.filter((engine) => !engine.available && !engine.custom)
  return off.length > 0 && off.length < engines.length ? new Set(off.map((engine) => engine.id)) : new Set()
}

/**
 * Lists the engines that are set up (every engine on request); each row saves on its own. An engine the
 * reader changed during this visit stays listed even when the change leaves it not set up (switched off,
 * key removed), so its note and the focus stay in view until the reader folds or unfolds the list.
 */
export function EnginesSection({ engines, loading, error, onRetry, onEngines, savedDefault, onDefaultSaved, settings, onSettingsSaved }: EnginesSectionProps) {
  const [showAll, setShowAll] = useState(false)
  const changed = useStayListed<string>()
  const folded = engines ? foldable(engines) : null
  const hiddenCount = folded ? [...folded].filter((id) => !changed.pinned.has(id)).length : 0
  return (
    <section aria-labelledby="settings-engines" className="rst-section">
      <SectionHeading id="settings-engines" note="Used by the assistant in the reader">
        AI engines
      </SectionHeading>
      {loading && !engines && (
        <div aria-busy="true" aria-label="Loading the AI engines">
          <Skeleton lines={4} />
        </div>
      )}
      {error && (
        <div className="rst-error" role="alert">
          <p className="r-error-text">{error}</p>
          <Button onClick={onRetry}>Try again</Button>
        </div>
      )}
      {engines && folded && (
        <>
          <DefaultEngine key={engines.map((engine) => `${engine.id}${engine.available}`).join(',')} engines={engines} saved={savedDefault} onSaved={onDefaultSaved} />
          <ul className="r-rows rst-engines">
            {/* Folded rows stay mounted, hidden, so a key or address typed into one is not lost. */}
            {engines.map((engine) => (
              <EngineItem
                key={engine.id}
                engine={engine}
                hidden={folded.has(engine.id) && !showAll && !changed.pinned.has(engine.id)}
                onChange={(updated) => {
                  changed.pin(engine.id, true)
                  onEngines(engines.map((entry) => (entry.id === updated.id ? { ...entry, ...updated } : entry)))
                }}
                onRemoved={(id) => onEngines(engines.filter((entry) => entry.id !== id))}
              />
            ))}
          </ul>
          {/* Unfolded, the button stays while any engine is not set up, even when every such row was changed. */}
          {(showAll ? folded.size > 0 : hiddenCount > 0) && (
            <Button
              variant="quiet"
              size="sm"
              onClick={() => {
                setShowAll((current) => !current)
                changed.release()
              }}
            >
              {showAll ? 'Show only the engines that are set up' : `Show the ${hiddenCount} ${hiddenCount === 1 ? 'engine that is' : 'engines that are'} not set up`}
            </Button>
          )}
          <CustomServer existingIds={engines.map((engine) => engine.id)} onAdded={(added) => onEngines([...engines, added])} />
          {/* Shown only when this copy of the service reports the setting (an older one does not). */}
          {settings && 'radar_llm_provider' in settings && onSettingsSaved && (
            <JudgingProviders engines={engines} settings={settings} onSaved={onSettingsSaved} />
          )}
        </>
      )}
    </section>
  )
}

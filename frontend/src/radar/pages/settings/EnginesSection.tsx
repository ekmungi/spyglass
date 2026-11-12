// EnginesSection: the "AI engines" group: the default engine and model, then one row per engine.
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

/** Lists every engine; each row saves on its own. */
export function EnginesSection({ engines, loading, error, onRetry, onEngines, savedDefault, onDefaultSaved, settings, onSettingsSaved }: EnginesSectionProps) {
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
      {engines && (
        <>
          <DefaultEngine key={engines.map((engine) => `${engine.id}${engine.available}`).join(',')} engines={engines} saved={savedDefault} onSaved={onDefaultSaved} />
          <ul className="r-rows rst-engines">
            {engines.map((engine) => (
              <EngineItem
                key={engine.id}
                engine={engine}
                onChange={(updated) => onEngines(engines.map((entry) => (entry.id === updated.id ? { ...entry, ...updated } : entry)))}
                onRemoved={(id) => onEngines(engines.filter((entry) => entry.id !== id))}
              />
            ))}
          </ul>
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

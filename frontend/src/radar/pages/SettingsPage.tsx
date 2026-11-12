// Settings page: AI engines (and which AI judges), privacy, the daily brief schedule, the vault folders, filing, the Send to Spyglass
// bookmark button and the theme. Each group saves on its own and reports success or failure
// beside its own button.
import './settings/settings.css'
import { Button, Skeleton } from '../ui'
import { loadEngines, loadSettings, type EngineRow, type SettingsValues } from './settings/api'
import { useRoute } from '../router'
import { AppearanceSection } from './settings/AppearanceSection'
import { BRING_IN_SECTION, BringInSection } from './settings/BringInSection'
import { BriefSection } from './settings/BriefSection'
import { EnginesSection } from './settings/EnginesSection'
import { FilingSection } from './settings/FilingSection'
import { PrivacySection } from './settings/PrivacySection'
import { UsageSection } from './settings/UsageSection'
import { VaultSection } from './settings/VaultSection'
import { useLoad } from './sources/useLoad'

/** The Settings page (no props). */
export default function SettingsPage() {
  const route = useRoute()
  const engines = useLoad<EngineRow[]>((signal) => loadEngines(signal))
  const settings = useLoad<SettingsValues>(() => loadSettings())
  const values = settings.data
  const saved = {
    engine: String(values?.assist_default_engine ?? ''),
    model: String(values?.assist_default_model ?? ''),
  }

  const merge = (stored: SettingsValues) => settings.replace({ ...(values ?? {}), ...stored })

  return (
    <div className="r-page rst-page">
      <h1 className="r-page-title">Settings</h1>
      <p className="r-page-meta">Which AI answers your questions, when the brief is made, and where saved notes go.</p>

      <EnginesSection
        engines={engines.data}
        loading={engines.loading}
        error={engines.error}
        onRetry={engines.reload}
        onEngines={engines.replace}
        savedDefault={saved}
        onDefaultSaved={(value) => merge({ assist_default_engine: value.engine, assist_default_model: value.model })}
        settings={values}
        onSettingsSaved={merge}
      />

      <PrivacySection />

      {settings.loading && !values && (
        <div aria-busy="true" aria-label="Loading your settings" className="rst-skeleton">
          <Skeleton lines={4} />
        </div>
      )}
      {settings.error && (
        <div className="rst-error" role="alert">
          <p className="r-error-text">{settings.error}</p>
          <Button onClick={settings.reload}>Try again</Button>
        </div>
      )}
      {values && (
        <>
          <BriefSection settings={values} onSaved={merge} />
          <VaultSection settings={values} onSaved={merge} />
          <FilingSection settings={values} onSaved={merge} />
        </>
      )}

      <BringInSection focus={route.name === 'settings' && route.section === BRING_IN_SECTION} />

      <UsageSection />

      <AppearanceSection />
    </div>
  )
}

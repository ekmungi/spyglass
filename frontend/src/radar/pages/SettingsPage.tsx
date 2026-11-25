// Settings page: six tabs (General, AI engines, Appearance, Bringing things in, Vault and filing, Privacy and usage).
// Each tab shows its own parts: AI engines (and which AI judges), privacy, the daily brief schedule, the vault folders, filing,
// the browser extension and the Send to Spyglass bookmark button, this computer (start with Windows, quit), the optional parts
// not installed, usage and the theme. Each part saves on its own and reports success or failure beside its own button.
import './settings/settings.css'
import { useState, type ReactNode } from 'react'
import { Button, Skeleton, Tabs } from '../ui'
import { loadEngines, loadSettings, type EngineRow, type SettingsValues } from './settings/api'
import { useRoute } from '../router'
import { AppearanceSection } from './settings/AppearanceSection'
import { BRING_IN_SECTION, BringInSection } from './settings/BringInSection'
import { BriefSection } from './settings/BriefSection'
import { DesktopSection } from './settings/DesktopSection'
import { EnginesSection } from './settings/EnginesSection'
import { FilingSection } from './settings/FilingSection'
import { PartsSection } from './settings/PartsSection'
import { PrivacySection } from './settings/PrivacySection'
import { SETTINGS_TABS, tabForSection, type SettingsTabKey } from './settings/settingsTabs'
import { UsageSection } from './settings/UsageSection'
import { VaultSection } from './settings/VaultSection'
import { useLoad } from './sources/useLoad'

interface PartProps {
  /** Whether this part's tab is the selected one. */
  on: boolean
  /**
   * True for a part with fields the reader types into before saving. Such a part keeps its state by
   * staying mounted, hidden, once its tab has been opened; the other parts leave the document.
   */
  holdsInput?: boolean
  /** Whether this part's tab has been opened at least once (nothing can have been typed before that). */
  opened: boolean
  children: ReactNode
}

/** One part of a tab: in the document while its tab is selected, and (if it holds typed input) kept hidden afterwards. */
function Part({ on, holdsInput = false, opened, children }: PartProps) {
  if (!holdsInput) return on ? <>{children}</> : null
  // The wrapper is always there for these parts, so hiding and showing never remounts (and never empties) the fields.
  return opened ? <div hidden={!on}>{children}</div> : null
}

/** The Settings page (no props). */
export default function SettingsPage() {
  const route = useRoute()
  const section = route.name === 'settings' ? route.section : undefined
  const [tab, setTab] = useState<SettingsTabKey>(() => tabForSection(section))
  const [openedTabs, setOpenedTabs] = useState<ReadonlySet<SettingsTabKey>>(() => new Set([tabForSection(section)]))
  const choose = (key: SettingsTabKey) => {
    setTab(key)
    setOpenedTabs((current) => new Set(current).add(key))
  }
  // An address that names a part (from a link on another page) opens the tab that holds it. This is
  // done while rendering, by comparing with the address seen last time, so no extra render is needed.
  const [seenSection, setSeenSection] = useState(section)
  if (section !== seenSection) {
    setSeenSection(section)
    if (section) choose(tabForSection(section))
  }

  const engines = useLoad<EngineRow[]>((signal) => loadEngines(signal))
  const settings = useLoad<SettingsValues>(() => loadSettings())
  const values = settings.data
  const saved = {
    engine: String(values?.assist_default_engine ?? ''),
    model: String(values?.assist_default_model ?? ''),
  }

  const merge = (stored: SettingsValues) => settings.replace({ ...(values ?? {}), ...stored })
  /** Props for the parts of one tab. */
  const at = (key: SettingsTabKey) => ({ on: tab === key, opened: openedTabs.has(key) })

  // The brief, vault and filing parts need the stored settings; their tabs show how loading is going.
  const settingsStatus = (
    <>
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
    </>
  )

  return (
    <div className="r-page r-page--wide rst-page">
      <h1 className="r-page-title">Settings</h1>
      <p className="r-page-meta">Which AI answers your questions, when the brief is made, and where saved notes go.</p>

      <Tabs tabs={SETTINGS_TABS} value={tab} onChange={(key) => choose(key as SettingsTabKey)} label="Settings" />

      <div role="tabpanel" className="rst-tabpanel" aria-label={SETTINGS_TABS.find((entry) => entry.key === tab)?.label}>
        {(tab === 'general' || tab === 'vault') && settingsStatus}

        <Part {...at('general')} holdsInput>
          {values && <BriefSection settings={values} onSaved={merge} />}
        </Part>
        <Part {...at('general')}>
          <DesktopSection />
        </Part>
        <Part {...at('general')}>
          <PartsSection />
        </Part>

        <Part {...at('engines')} holdsInput>
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
        </Part>

        <Part {...at('appearance')}>
          <AppearanceSection />
        </Part>

        <Part {...at('bring-in')}>
          <BringInSection focus={route.name === 'settings' && route.section === BRING_IN_SECTION} />
        </Part>

        <Part {...at('vault')} holdsInput>
          {values && (
            <>
              <VaultSection settings={values} onSaved={merge} />
              <FilingSection settings={values} onSaved={merge} />
            </>
          )}
        </Part>

        <Part {...at('privacy')}>
          <PrivacySection />
          <UsageSection />
        </Part>
      </div>
    </div>
  )
}

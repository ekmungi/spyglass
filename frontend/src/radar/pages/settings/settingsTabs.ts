// settingsTabs: the six tabs of the Settings page and which part (section) sits on which tab. A part is
// named by the end of its heading id, so "vault" is the part whose heading id is "settings-vault".
import type { TabItem } from '../../ui'

export type SettingsTabKey = 'general' | 'engines' | 'appearance' | 'bring-in' | 'vault' | 'privacy'

/** The strip, in the order the reader sees it. */
export const SETTINGS_TABS: TabItem[] = [
  { key: 'general', label: 'General' },
  { key: 'engines', label: 'AI engines' },
  { key: 'appearance', label: 'Appearance' },
  { key: 'bring-in', label: 'Bringing things in' },
  { key: 'vault', label: 'Vault and filing' },
  { key: 'privacy', label: 'Privacy and usage' },
]

/** The parts on each tab, in the order they appear inside it. */
const PARTS_OF_TAB: Record<SettingsTabKey, readonly string[]> = {
  general: ['brief', 'desktop', 'parts'],
  engines: ['engines'],
  appearance: ['appearance'],
  'bring-in': ['extension', 'bring-in'],
  vault: ['vault', 'filing'],
  privacy: ['privacy', 'usage'],
}

/** The tab that holds a part, for the `section` of the address. A missing or unknown part gives General. */
export function tabForSection(section: string | undefined): SettingsTabKey {
  const found = (Object.keys(PARTS_OF_TAB) as SettingsTabKey[]).find((tab) => section !== undefined && PARTS_OF_TAB[tab].includes(section))
  return found ?? 'general'
}

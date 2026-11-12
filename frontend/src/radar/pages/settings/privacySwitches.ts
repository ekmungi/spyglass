// privacySwitches: the four privacy switches, in the order shown, each with the one honest line the
// reader agrees to. Each is saved through PATCH /api/settings under its key.
import type { PrivacySwitchKey } from '../../api/types'

export const PRIVACY_SWITCHES: { key: PrivacySwitchKey; label: string }[] = [
  { key: 'privacy_send_examples', label: 'Send titles of items I saved as examples of my taste' },
  { key: 'privacy_proxy_images', label: 'Load article images through Spyglass, so the sites never see my browser' },
  {
    key: 'privacy_allow_bot_checks',
    label: "Let the built-in browser complete a site's automated check (sends technical details of that browser, never anything personal)",
  },
  { key: 'jina_enabled', label: 'Use an outside rendering service for pages that block Spyglass (it learns which pages I read)' },
]

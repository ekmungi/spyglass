// store.js - where the extension keeps its two settings: the address of Spyglass and the key.
// They live in chrome.storage.local, on this computer only. The key is never logged or shown
// anywhere except in the masked field of the settings page.

import { DEFAULT_ADDRESS, normalizeAddress } from './lib.js'

/**
 * Read the saved settings; an unusable saved address falls back to the default.
 * @returns {Promise<{address: string, key: string}>}
 */
export async function loadSettings() {
  const saved = await chrome.storage.local.get({ address: DEFAULT_ADDRESS, key: '' })
  const checked = normalizeAddress(saved.address)
  return { address: checked.ok ? checked.address : DEFAULT_ADDRESS, key: String(saved.key || '') }
}

/**
 * Save the settings (the caller has already checked both values with lib.js).
 * @param {{address: string, key: string}} settings
 * @returns {Promise<void>}
 */
export async function saveSettings(settings) {
  await chrome.storage.local.set({ address: settings.address, key: settings.key })
}

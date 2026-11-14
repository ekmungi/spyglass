// store.js - where the extension keeps its two settings: the address of Spyglass and the key.
// They live in chrome.storage.local, on this computer only. The key is never logged or shown
// anywhere except in the masked field of the settings page.

import { DEFAULT_ADDRESS, chooseBundledSettings, normalizeAddress } from './lib.js'

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

/**
 * Read spyglass-config.json, which Spyglass writes beside this file in the copy of the extension
 * the reader loaded. A missing or unreadable file is not an error: there is just nothing to adopt.
 * @returns {Promise<{address: string, key: string, stamp: string} | null>}
 */
async function readBundledConfig() {
  try {
    const response = await fetch(chrome.runtime.getURL('spyglass-config.json'))
    if (!response.ok) return null
    const data = await response.json()
    return data && typeof data === 'object' ? data : null
  } catch {
    return null
  }
}

/**
 * Take the address and key from the bundled file when its stamp is new, and remember the stamp.
 * Called at start-up and when the settings page opens, so a reload picks up a new key.
 * @returns {Promise<boolean>} whether anything was saved
 */
export async function adoptBundledConfig() {
  const bundled = await readBundledConfig()
  if (!bundled) return false
  const saved = await chrome.storage.local.get({ address: DEFAULT_ADDRESS, key: '', stamp: '' })
  const chosen = chooseBundledSettings(saved, bundled)
  if (!chosen) return false
  await chrome.storage.local.set({ address: chosen.address, key: chosen.key, stamp: chosen.stamp })
  return true
}

// options.js - the settings page. It checks the address and the key with lib.js, saves them in
// chrome.storage.local, and "Test connection" asks Spyglass whether they are right. The key sits
// in a masked field and is never logged. All messages are shown with textContent.

import { checkSpyglass, describeOutcome, normalizeAddress, normalizeKey } from './lib.js'
import { loadSettings, saveSettings } from './store.js'

const form = document.getElementById('form')
const addressField = document.getElementById('address')
const keyField = document.getElementById('key')
const revealButton = document.getElementById('reveal')
const testButton = document.getElementById('test')
const status = document.getElementById('status')

/**
 * Show a message under the buttons.
 * @param {string} message
 * @param {'ok' | 'error' | ''} tone
 */
function say(message, tone = '') {
  status.textContent = message
  status.className = tone ? `status ${tone}` : 'status'
}

/**
 * Check both fields. Says what is wrong and returns null, or returns the clean values.
 * @returns {{address: string, key: string} | null}
 */
function readFields() {
  const address = normalizeAddress(addressField.value)
  if (!address.ok) {
    say(address.message, 'error')
    return null
  }
  const key = normalizeKey(keyField.value)
  if (!key.ok) {
    say(key.message, 'error')
    return null
  }
  return { address: address.address, key: key.key }
}

/**
 * Save the settings if both fields are fine.
 * @returns {Promise<{address: string, key: string} | null>} the saved values, or null
 */
async function save() {
  const values = readFields()
  if (!values) return null
  await saveSettings(values)
  addressField.value = values.address
  return values
}

form.addEventListener('submit', async (event) => {
  event.preventDefault()
  if (await save()) say('Saved.', 'ok')
})

// Testing saves first, so a working connection is never left unsaved.
testButton.addEventListener('click', async () => {
  const values = await save()
  if (!values) return
  testButton.disabled = true
  say('Testing…')
  const result = describeOutcome(await checkSpyglass(values), 'check')
  say(result.ok ? `Saved. ${result.message}` : result.message, result.ok ? 'ok' : 'error')
  testButton.disabled = false
})

revealButton.addEventListener('click', () => {
  const show = keyField.type === 'password'
  keyField.type = show ? 'text' : 'password'
  revealButton.textContent = show ? 'Hide' : 'Show'
  revealButton.setAttribute('aria-pressed', String(show))
})

loadSettings().then((settings) => {
  addressField.value = settings.address
  keyField.value = settings.key
})

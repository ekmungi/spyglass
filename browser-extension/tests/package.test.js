// package.test.js - checks the extension as a package: the manifest parses, every file it names
// exists, it asks for no more than it needs, and no script uses remote code, eval or HTML injection.
// Run from the Spyglass folder:  node --test browser-extension/tests/*.test.js
// (The logic in lib.js is tested by the interface's test run: frontend/src/radar/extension/lib.test.ts.)

import assert from 'node:assert/strict'
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const manifest = JSON.parse(readFileSync(join(root, 'manifest.json'), 'utf8'))
const appManifest = JSON.parse(readFileSync(join(root, '..', 'manifest.json'), 'utf8'))
const sources = readdirSync(root).filter((name) => /\.(js|html)$/.test(name))

/** The PNG signature, then the width and height stored in the IHDR chunk. */
function pngSize(path) {
  const bytes = readFileSync(path)
  assert.equal(bytes.subarray(0, 8).toString('hex'), '89504e470d0a1a0a', `${path} is not a PNG`)
  return [bytes.readUInt32BE(16), bytes.readUInt32BE(20)]
}

test('the manifest has the same version as the app', () => {
  assert.equal(manifest.manifest_version, 3)
  assert.equal(manifest.version, appManifest.version)
})

test('it asks for only the permissions it uses, and only the local computer as a host', () => {
  assert.deepEqual([...manifest.permissions].sort(), ['activeTab', 'contextMenus', 'notifications', 'scripting', 'storage'])
  assert.deepEqual(manifest.host_permissions, ['http://localhost/*', 'http://127.0.0.1/*'])
})

test('every file the manifest names exists', () => {
  const named = [
    manifest.action.default_popup,
    manifest.background.service_worker,
    manifest.options_ui.page,
    ...Object.values(manifest.icons),
    ...Object.values(manifest.action.default_icon),
  ]
  assert.ok(named.length >= 11)
  for (const file of named) assert.ok(existsSync(join(root, file)), `missing: ${file}`)
})

test('the icons are real PNG files of the sizes they are named for', () => {
  for (const size of [16, 32, 48, 128]) {
    assert.equal(manifest.icons[String(size)], `icons/icon-${size}.png`)
    assert.deepEqual(pngSize(join(root, manifest.icons[String(size)])), [size, size])
  }
})

test('it has a strict content security policy and a keyboard command', () => {
  const policy = manifest.content_security_policy.extension_pages
  assert.match(policy, /script-src 'self'/)
  assert.doesNotMatch(policy, /unsafe-eval|unsafe-inline|https?:/)
  assert.equal(manifest.commands['send-page'].suggested_key.default, 'Alt+Shift+S')
})

test('every page and script the extension loads is a file of this folder', () => {
  const html = sources.filter((name) => name.endsWith('.html'))
  assert.ok(html.length >= 2)
  for (const name of html) {
    const text = readFileSync(join(root, name), 'utf8')
    for (const [, address] of text.matchAll(/(?:src|href)="([^"]+)"/g)) {
      assert.ok(existsSync(join(root, address)), `${name} loads ${address}, which is missing`)
      assert.ok(!/^[a-z]+:/.test(address), `${name} loads a remote file: ${address}`)
    }
  }
  for (const name of sources.filter((file) => file.endsWith('.js'))) {
    const text = readFileSync(join(root, name), 'utf8')
    for (const [, address] of text.matchAll(/from '(\.[^']+)'/g)) {
      assert.ok(existsSync(join(root, address)), `${name} imports ${address}, which is missing`)
    }
  }
})

test('no script uses remote code, eval or HTML injection, and every script starts with a comment', () => {
  for (const name of sources) {
    const text = readFileSync(join(root, name), 'utf8')
    assert.doesNotMatch(text, /\beval\s*\(|new Function\s*\(|importScripts\s*\(|document\.write\s*\(/, name)
    assert.doesNotMatch(text, /\.innerHTML\s*=|insertAdjacentHTML|outerHTML\s*=/, name)
    if (name.endsWith('.js')) assert.ok(text.startsWith('//'), `${name} has no comment at the top`)
  }
  assert.ok(statSync(join(root, 'lib.js')).size > 0)
})

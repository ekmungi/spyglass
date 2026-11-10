// Tests for pure lifecycle helpers: URLs and the service spawn specification.
import { describe, expect, it } from 'vitest'
import { dashboardUrl, healthUrl, needsRepoPath, REPO_PATH_NOTICE, spawnSpec } from './lifecycle'

describe('needsRepoPath', () => {
  it('asks for the repository folder when it is blank and the plugin manages the service', () => {
    expect(needsRepoPath({ repoPath: '', connectOnly: false })).toBe(true)
    expect(needsRepoPath({ repoPath: '   ', connectOnly: false })).toBe(true)
  })

  it('does not ask once a folder is set', () => {
    expect(needsRepoPath({ repoPath: 'C:/Dev/spyglass', connectOnly: false })).toBe(false)
  })

  it('does not ask in connect-only mode, where the plugin never starts the service', () => {
    expect(needsRepoPath({ repoPath: '', connectOnly: true })).toBe(false)
  })

  it('tells the user where to set the folder', () => {
    expect(REPO_PATH_NOTICE).toContain('Service repository path')
  })
})

describe('urls', () => {
  it('builds localhost urls from the configured port', () => {
    expect(healthUrl(7777)).toBe('http://127.0.0.1:7777/api/health')
    expect(dashboardUrl(7901)).toBe('http://127.0.0.1:7901/')
  })
})

describe('spawnSpec', () => {
  it('runs the repo venv python as a hidden module process', () => {
    const spec = spawnSpec({ repoPath: 'C:/Dev/spyglass', port: 7901 })
    expect(spec.command).toBe('C:/Dev/spyglass/.venv/Scripts/python.exe')
    expect(spec.args).toEqual(['-m', 'spyglass_service'])
    expect(spec.options.cwd).toBe('C:/Dev/spyglass')
    expect(spec.options.windowsHide).toBe(true)
    expect(spec.options.env.SPYGLASS_PORT).toBe('7901')
  })

  it('passes vault path and research folder as env when provided', () => {
    const spec = spawnSpec({
      repoPath: 'C:/Dev/spyglass',
      port: 7777,
      vaultPath: 'C:/Vault',
      researchFolder: '03 RESOURCES/Research/Spyglass',
    })
    expect(spec.options.env.SPYGLASS_VAULT_PATH).toBe('C:/Vault')
    expect(spec.options.env.SPYGLASS_BRIEFING_SUBDIR).toBe('03 RESOURCES/Research/Spyglass')
  })

  it('passes SPYGLASS_DATA_DIR when dataDir is non-empty', () => {
    const spec = spawnSpec({ repoPath: 'C:/Dev/spyglass', port: 7777, dataDir: 'C:/x' })
    expect(spec.options.env.SPYGLASS_DATA_DIR).toBe('C:/x')
  })

  it('omits SPYGLASS_DATA_DIR when dataDir is absent or blank', () => {
    const specAbsent = spawnSpec({ repoPath: 'C:/Dev/spyglass', port: 7777 })
    expect(specAbsent.options.env.SPYGLASS_DATA_DIR).toBeUndefined()
    const specBlank = spawnSpec({ repoPath: 'C:/Dev/spyglass', port: 7777, dataDir: '' })
    expect(specBlank.options.env.SPYGLASS_DATA_DIR).toBeUndefined()
  })
})

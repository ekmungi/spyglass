// Tests for the service supervisor: start, already-running, failure, stop.
import { describe, expect, it, vi } from 'vitest'
import { ServiceManager } from './service'

function makeManager(healthSequence: boolean[], spawnImpl?: () => { pid: number }) {
  const health = [...healthSequence]
  const fetchHealthy = vi.fn(async () => (health.length > 1 ? health.shift()! : health[0]))
  const spawnFn = vi.fn(spawnImpl ?? (() => ({ pid: 4242 })))
  const shutdownFn = vi.fn(async () => true)
  const killFn = vi.fn()
  const manager = new ServiceManager({
    repoPath: 'C:/Dev/spyglass',
    port: 7777,
    fetchHealthy,
    spawnFn,
    shutdownFn,
    killFn,
    pollMs: 1,
    timeoutMs: 50,
  })
  return { manager, fetchHealthy, spawnFn, shutdownFn, killFn }
}

describe('ServiceManager.ensureRunning', () => {
  it('does not spawn when the service already answers health checks', async () => {
    const { manager, spawnFn } = makeManager([true])
    expect(await manager.ensureRunning()).toBe('already-running')
    expect(spawnFn).not.toHaveBeenCalled()
  })

  it('spawns and waits until health flips to ok', async () => {
    const { manager, spawnFn } = makeManager([false, false, true])
    expect(await manager.ensureRunning()).toBe('started')
    expect(spawnFn).toHaveBeenCalledOnce()
  })

  it('reports failure when the service never becomes healthy', async () => {
    const { manager } = makeManager([false])
    expect(await manager.ensureRunning()).toBe('failed')
  })
})

describe('ServiceManager.stop', () => {
  it('asks for a graceful shutdown first', async () => {
    const { manager, shutdownFn, killFn } = makeManager([false, false, true])
    await manager.ensureRunning()
    await manager.stop()
    expect(shutdownFn).toHaveBeenCalled()
    expect(killFn).not.toHaveBeenCalled()
  })

  it('falls back to killing the process tree when shutdown fails', async () => {
    const { manager, killFn } = makeManager([false, false, true])
    const failingShutdown = vi.fn(async () => false)
    ;(manager as unknown as { deps: { shutdownFn: typeof failingShutdown } }).deps.shutdownFn =
      failingShutdown
    await manager.ensureRunning()
    await manager.stop()
    expect(killFn).toHaveBeenCalledWith(4242)
  })
})

describe('ServiceManager.restart', () => {
  it('shuts the running service down, waits for it to drop, then respawns', async () => {
    // health: up, then down (drop confirmed), then down (ensureRunning), then up (respawned).
    const { manager, shutdownFn, spawnFn } = makeManager([true, false, false, true])
    const result = await manager.restart()
    expect(shutdownFn).toHaveBeenCalled()
    expect(spawnFn).toHaveBeenCalledOnce()
    expect(result).toBe('started')
  })

  it('hard-kills the tree on restart when graceful shutdown fails and a pid is known', async () => {
    const { manager, killFn } = makeManager([false, false, true])
    const failingShutdown = vi.fn(async () => false)
    ;(manager as unknown as { deps: { shutdownFn: typeof failingShutdown } }).deps.shutdownFn =
      failingShutdown
    await manager.ensureRunning() // spawns pid 4242
    await manager.restart() // graceful shutdown fails -> kill the known pid
    expect(killFn).toHaveBeenCalledWith(4242)
  })
})

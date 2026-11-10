// Tests for AutoRefresher (tick logic) and formatLastRefreshed (status text).
import { describe, expect, it, vi } from 'vitest'
import { AutoRefresher, formatLastRefreshed, healthyForRefresh } from './autorefresh'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Build an AutoRefresher with fully-controllable deps. */
function makeRefresher({
  healthy = true,
  refreshResult = true,
  nowMs = 1_000_000,
  intervalMs = 60_000,
  maxBackoffMs = 6 * 60 * 60 * 1000,
}: {
  healthy?: boolean
  refreshResult?: boolean
  nowMs?: number
  intervalMs?: number
  maxBackoffMs?: number
} = {}) {
  let clock = nowMs
  const isHealthy = vi.fn(async () => healthy)
  const refresh = vi.fn(async () => refreshResult)
  const onRefreshed = vi.fn()
  const now = () => clock
  const ar = new AutoRefresher({ isHealthy, refresh, onRefreshed, now }, intervalMs, maxBackoffMs)
  return { ar, isHealthy, refresh, onRefreshed, clock: { set: (ms: number) => { clock = ms } } }
}

// ---------------------------------------------------------------------------
// AutoRefresher.tick
// ---------------------------------------------------------------------------

describe('AutoRefresher.tick', () => {
  it('returns refreshed and calls onRefreshed when healthy and refresh succeeds', async () => {
    const { ar, onRefreshed } = makeRefresher({ nowMs: 1_000_000 })
    const result = await ar.tick()
    expect(result).toBe('refreshed')
    expect(onRefreshed).toHaveBeenCalledWith(1_000_000)
  })

  it('returns unhealthy and does not call refresh when service is down', async () => {
    const { ar, refresh, onRefreshed } = makeRefresher({ healthy: false })
    const result = await ar.tick()
    expect(result).toBe('unhealthy')
    expect(refresh).not.toHaveBeenCalled()
    expect(onRefreshed).not.toHaveBeenCalled()
  })

  it('returns failed when refresh returns false and sets backoff', async () => {
    const { ar } = makeRefresher({ refreshResult: false, nowMs: 1_000_000, intervalMs: 60_000 })
    const result = await ar.tick()
    expect(result).toBe('failed')
  })

  it('skips within the backoff window after a failure', async () => {
    const nowMs = 1_000_000
    const intervalMs = 60_000
    const { ar, clock } = makeRefresher({ refreshResult: false, nowMs, intervalMs })
    // First tick: fails, sets backoff to now + intervalMs * 2^1 = +120_000
    await ar.tick()
    // Move time forward but stay within the backoff window
    clock.set(nowMs + 60_000)
    const result = await ar.tick()
    expect(result).toBe('skipped')
  })

  it('retries after the backoff window expires', async () => {
    let calls = 0
    const nowMs = 1_000_000
    const intervalMs = 60_000
    // Override refresh: fail once, then succeed
    const isHealthy = vi.fn(async () => true)
    const refreshFn = vi.fn(async () => {
      calls++
      return calls > 1
    })
    const onRefreshed = vi.fn()
    const clockObj = { val: nowMs }
    const refresher = new AutoRefresher(
      { isHealthy, refresh: refreshFn, onRefreshed, now: () => clockObj.val },
      intervalMs,
    )
    // Tick 1: fails (backoff = now + 120_000)
    expect(await refresher.tick()).toBe('failed')
    // Within backoff: skipped
    clockObj.val = nowMs + 60_000
    expect(await refresher.tick()).toBe('skipped')
    // Past backoff window: retried and succeeds
    clockObj.val = nowMs + 130_000
    expect(await refresher.tick()).toBe('refreshed')
    expect(onRefreshed).toHaveBeenCalledWith(nowMs + 130_000)
  })

  it('resets backoff after a success', async () => {
    let calls = 0
    const nowMs = 1_000_000
    const intervalMs = 60_000
    const isHealthy = vi.fn(async () => true)
    const refreshFn = vi.fn(async () => {
      calls++
      // fail first, succeed second
      return calls !== 1
    })
    const onRefreshed = vi.fn()
    const clockObj = { val: nowMs }
    const ar = new AutoRefresher(
      { isHealthy, refresh: refreshFn, onRefreshed, now: () => clockObj.val },
      intervalMs,
    )
    // Fail -> sets backoff
    expect(await ar.tick()).toBe('failed')
    // Skip past backoff
    clockObj.val = nowMs + 130_000
    // Succeed -> resets backoff (nextAllowed = 0)
    expect(await ar.tick()).toBe('refreshed')
    // Immediate next tick should NOT be skipped (nextAllowed == 0 <= now)
    clockObj.val = nowMs + 130_001
    expect(await ar.tick()).toBe('refreshed')
  })

  it('returns skipped when a tick is already in flight', async () => {
    // refresh never resolves during test -- we capture the resolve handle
    let resolveRefresh!: (v: boolean) => void
    const refresh = vi.fn(
      () =>
        new Promise<boolean>((res) => {
          resolveRefresh = res
        }),
    )
    const ar = new AutoRefresher(
      {
        isHealthy: async () => true,
        refresh,
        onRefreshed: vi.fn(),
        now: () => Date.now(),
      },
      60_000,
    )
    // Start first tick but do not await
    const first = ar.tick()
    // Second tick should be skipped immediately
    const second = await ar.tick()
    expect(second).toBe('skipped')
    // Resolve the first so the test can clean up
    resolveRefresh(true)
    await first
  })

  it('caps backoff at maxBackoffMs', async () => {
    const nowMs = 1_000_000
    const intervalMs = 60_000
    const maxBackoffMs = 90_000
    const refreshFn = vi.fn(async () => false)
    const clockObj = { val: nowMs }
    const ar = new AutoRefresher(
      {
        isHealthy: async () => true,
        refresh: refreshFn,
        onRefreshed: vi.fn(),
        now: () => clockObj.val,
      },
      intervalMs,
      maxBackoffMs,
    )
    // Tick 1: fails -- failures=1, backoff = min(60000*2, 90000) = 90000
    await ar.tick()
    // Jump past first backoff
    clockObj.val = nowMs + 91_000
    // Tick 2: fails -- failures=2, backoff = min(60000*4, 90000) = 90000 (capped)
    await ar.tick()
    // 45_000ms after tick 2 -- within the 90_000ms cap
    clockObj.val = nowMs + 91_000 + 45_000
    expect(await ar.tick()).toBe('skipped')
    // 95_000ms after tick 2 -- past the cap
    clockObj.val = nowMs + 91_000 + 95_000
    expect(await ar.tick()).toBe('failed')
  })
})

describe('AutoRefresher.forceTick', () => {
  it('bypasses backoff and calls refresh directly', async () => {
    const nowMs = 1_000_000
    const intervalMs = 60_000
    const refreshFn = vi.fn(async () => false)
    const clockObj = { val: nowMs }
    const onRefreshed = vi.fn()
    const ar = new AutoRefresher(
      {
        isHealthy: async () => true,
        refresh: refreshFn,
        onRefreshed,
        now: () => clockObj.val,
      },
      intervalMs,
    )
    // Fail to set backoff
    await ar.tick()
    // Still within backoff -- forceTick should bypass it
    clockObj.val = nowMs + 30_000
    const secondRefresh = vi.fn(async () => true)
    ;(ar as unknown as { deps: { refresh: typeof secondRefresh } }).deps.refresh = secondRefresh
    const result = await ar.forceTick()
    expect(result).toBe('refreshed')
    expect(onRefreshed).toHaveBeenCalledWith(nowMs + 30_000)
  })
})

// ---------------------------------------------------------------------------
// formatLastRefreshed
// ---------------------------------------------------------------------------

describe('formatLastRefreshed', () => {
  it('returns never refreshed when lastAtMs is null', () => {
    expect(formatLastRefreshed(null, 1_000_000)).toBe('Spyglass: never refreshed')
  })

  it('returns just now for 0-59 seconds ago', () => {
    const now = 1_000_000
    expect(formatLastRefreshed(now - 30_000, now)).toBe('Spyglass: refreshed just now')
    expect(formatLastRefreshed(now, now)).toBe('Spyglass: refreshed just now')
    expect(formatLastRefreshed(now - 59_000, now)).toBe('Spyglass: refreshed just now')
  })

  it('returns minutes ago for 1-59 minutes', () => {
    const now = 10_000_000
    expect(formatLastRefreshed(now - 60_000, now)).toBe('Spyglass: refreshed 1m ago')
    expect(formatLastRefreshed(now - 14 * 60_000, now)).toBe('Spyglass: refreshed 14m ago')
    expect(formatLastRefreshed(now - 59 * 60_000, now)).toBe('Spyglass: refreshed 59m ago')
  })

  it('returns hours ago for 60+ minutes', () => {
    const now = 100_000_000
    expect(formatLastRefreshed(now - 60 * 60_000, now)).toBe('Spyglass: refreshed 1h ago')
    expect(formatLastRefreshed(now - 3 * 60 * 60_000, now)).toBe('Spyglass: refreshed 3h ago')
  })
})

describe('healthyForRefresh', () => {
  it('is healthy only when up (200) and db is ok', () => {
    expect(healthyForRefresh(200, { db: 'ok' })).toBe(true)
    expect(healthyForRefresh(200, { db: 'unhealthy' })).toBe(false)
    expect(healthyForRefresh(503, { db: 'ok' })).toBe(false)
    expect(healthyForRefresh(200, null)).toBe(false)
    expect(healthyForRefresh(200, {})).toBe(false)
  })
})

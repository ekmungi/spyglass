// Tests for the first-start client functions and for waitForService, which polls /api/health.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { dismissSetupGuide, getFirstStart, saveFirstStart } from './client'
import { ApiError } from './errors'
import { setFetchForTesting } from './transport'
import { waitForService } from './waitForService'

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status })

afterEach(() => {
  setFetchForTesting(null)
  vi.useRealTimers()
})

describe('first-start client functions', () => {
  it('reads the first-start answer from GET /api/radar/desktop/first-start', async () => {
    const reply = { needed: true, data_dir: 'C:\\Data', vault_path: null, browsers: [{ id: 'chrome', name: 'Chrome' }] }
    const fetcher = vi.fn().mockResolvedValue(json(reply))
    setFetchForTesting(fetcher)
    await expect(getFirstStart()).resolves.toEqual(reply)
    expect(fetcher.mock.calls[0][0]).toBe('/api/radar/desktop/first-start')
    expect(fetcher.mock.calls[0][1].method).toBe('GET')
  })

  it('posts the chosen folder and vault and returns the reply', async () => {
    const fetcher = vi.fn().mockResolvedValue(json({ restart: true, data_dir: 'D:\\Spy' }))
    setFetchForTesting(fetcher)
    await expect(saveFirstStart({ data_dir: 'D:\\Spy', vault_path: null })).resolves.toEqual({ restart: true, data_dir: 'D:\\Spy' })
    expect(fetcher.mock.calls[0][1].method).toBe('POST')
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ data_dir: 'D:\\Spy', vault_path: null })
  })

  it('throws an ApiError carrying the sentence of a 400', async () => {
    setFetchForTesting(vi.fn().mockResolvedValue(json({ detail: 'That folder cannot be used.' }, 400)))
    const failure = await saveFirstStart({ data_dir: 'x', vault_path: null }).catch((error: unknown) => error)
    expect(failure).toBeInstanceOf(ApiError)
    expect((failure as ApiError).message).toBe('That folder cannot be used.')
  })

  it('posts to the dismiss route and accepts a 204', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    setFetchForTesting(fetcher)
    await expect(dismissSetupGuide()).resolves.toBeNull()
    expect(fetcher.mock.calls[0][0]).toBe('/api/radar/desktop/setup-guide/dismiss')
    expect(fetcher.mock.calls[0][1].method).toBe('POST')
  })
})

describe('waitForService', () => {
  beforeEach(() => vi.useFakeTimers())

  it('answers true as soon as /api/health answers 200', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }))
    setFetchForTesting(fetcher)
    await expect(waitForService()).resolves.toBe(true)
    expect(fetcher.mock.calls[0][0]).toBe('/api/health')
  })

  it('keeps polling once a second while the service does not answer', async () => {
    const fetcher = vi
      .fn()
      .mockRejectedValueOnce(new TypeError('down'))
      .mockResolvedValueOnce(new Response('{}', { status: 503 }))
      .mockResolvedValue(new Response('{}', { status: 200 }))
    setFetchForTesting(fetcher)
    const result = waitForService()
    await vi.advanceTimersByTimeAsync(2000)
    await expect(result).resolves.toBe(true)
    expect(fetcher).toHaveBeenCalledTimes(3)
  })

  it('gives up with false after the time limit', async () => {
    setFetchForTesting(vi.fn().mockRejectedValue(new TypeError('down')))
    const result = waitForService({ timeoutMs: 5000 })
    await vi.advanceTimersByTimeAsync(6000)
    await expect(result).resolves.toBe(false)
  })

  it('with afterStop, ignores an answer from the old service until it has gone quiet once', async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(new Response('{}', { status: 200 }))
      .mockResolvedValueOnce(new Response('{}', { status: 200 }))
      .mockRejectedValueOnce(new TypeError('down'))
      .mockResolvedValue(new Response('{}', { status: 200 }))
    setFetchForTesting(fetcher)
    const result = waitForService({ afterStop: true })
    await vi.advanceTimersByTimeAsync(3000)
    await expect(result).resolves.toBe(true)
    expect(fetcher).toHaveBeenCalledTimes(4)
  })

  it('with afterStop, accepts an answer after the grace period even if it never saw the service stop', async () => {
    setFetchForTesting(vi.fn().mockResolvedValue(new Response('{}', { status: 200 })))
    const result = waitForService({ afterStop: true, stopGraceMs: 3000 })
    await vi.advanceTimersByTimeAsync(4000)
    await expect(result).resolves.toBe(true)
  })
})

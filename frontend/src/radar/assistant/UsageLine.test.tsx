// Tests for the usage line under an answer: figures when they exist, nothing when they do not, and
// the note about a condensed conversation.
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { clearMessageUsage } from '../api/usage'
import { setFetchForTesting } from '../api/transport'
import { UsageLine } from './UsageLine'

beforeEach(() => clearMessageUsage())
afterEach(() => {
  cleanup()
  setFetchForTesting(null)
})

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status })

describe('UsageLine', () => {
  it('shows what the model read, from cache and wrote', async () => {
    setFetchForTesting(async () => json({ context_tokens: 12400, cached_share: 0.91, output_tokens: 380, model: 'haiku' }))
    render(<UsageLine messageId={5} finished />)
    expect(await screen.findByTestId('usage-line')).toHaveTextContent('haiku · Read 12,400 tokens, 91% from cache · wrote 380')
    expect(screen.queryByText(/condensed/)).toBeNull()
  })

  it('says when earlier messages were condensed', async () => {
    setFetchForTesting(async () => json({ context_tokens: 900, output_tokens: 10, condensed: true }))
    render(<UsageLine messageId={6} finished />)
    expect(await screen.findByText('Earlier messages were condensed to save usage.')).toBeInTheDocument()
  })

  it('shows nothing when no figures were kept', async () => {
    let asked = 0
    setFetchForTesting(async () => {
      asked += 1
      return json({ detail: 'No usage was recorded for that answer.' }, 404)
    })
    const { container } = render(<UsageLine messageId={7} finished />)
    await new Promise((resolve) => setTimeout(resolve, 30))
    expect(asked).toBe(1)
    expect(container).toBeEmptyDOMElement()
  })

  it('does not ask before the answer is finished or stored', async () => {
    let asked = 0
    setFetchForTesting(async () => {
      asked += 1
      return json({})
    })
    render(<UsageLine messageId={8} finished={false} />)
    render(<UsageLine messageId={null} finished />)
    await new Promise((resolve) => setTimeout(resolve, 30))
    expect(asked).toBe(0)
  })

  it('stays quiet when the request itself fails', async () => {
    setFetchForTesting(async () => {
      throw new TypeError('network down')
    })
    const { container } = render(<UsageLine messageId={9} finished />)
    await new Promise((resolve) => setTimeout(resolve, 30))
    expect(container).toBeEmptyDOMElement()
  })
})

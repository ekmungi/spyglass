// Tests for embedUrl: only known player origins may be embedded in the reader's player iframe.
import { describe, expect, it } from 'vitest'
import { embedUrl } from './embed'

describe('embedUrl', () => {
  it('turns YouTube and Vimeo page addresses into player addresses', () => {
    expect(embedUrl('https://www.youtube.com/watch?v=abc123', false)).toBe('https://www.youtube-nocookie.com/embed/abc123')
    expect(embedUrl('https://youtu.be/abc123', false)).toBe('https://www.youtube-nocookie.com/embed/abc123')
    expect(embedUrl('https://www.youtube.com/embed/abc123', false)).toBe('https://www.youtube.com/embed/abc123')
    expect(embedUrl('https://www.youtube-nocookie.com/embed/abc123', false)).toBe('https://www.youtube-nocookie.com/embed/abc123')
    expect(embedUrl('https://vimeo.com/76979871', false)).toBe('https://player.vimeo.com/video/76979871')
    expect(embedUrl('https://player.vimeo.com/video/76979871', false)).toBe('https://player.vimeo.com/video/76979871')
  })

  it('refuses addresses that are not on the player list', () => {
    expect(embedUrl(null, false)).toBeNull()
    expect(embedUrl('not a url', false)).toBeNull()
    expect(embedUrl('javascript:alert(1)', false)).toBeNull()
    expect(embedUrl('http://example.org/video', false)).toBeNull()
    expect(embedUrl('https://example.org/video', false)).toBeNull()
    expect(embedUrl('https://www.youtube.com/watch', false)).toBeNull()
    expect(embedUrl('https://evil.example/embed/abc123', false)).toBeNull()
    expect(embedUrl('https://www.youtube.com.evil.example/embed/abc', false)).toBeNull()
    expect(embedUrl('https://www.youtube.com' + '@evil.example/embed/abc', false)).toBeNull()
    expect(embedUrl('https://vimeo.com/not-a-number', false)).toBeNull()
  })

  it('accepts the inline stand-in player only in sample mode', () => {
    const inline = 'data:text/html,<p>player</p>'
    expect(embedUrl(inline, true)).toBe(inline)
    expect(embedUrl(inline, false)).toBeNull()
  })
})

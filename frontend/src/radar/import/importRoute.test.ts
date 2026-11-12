import { describe, expect, it } from 'vitest'
import { buildHash, parseHash, type Route } from '../router'

const TOKEN = '0123456789abcdef0123456789abcdef'

describe('the import window route', () => {
  it('reads a well-formed token or error code and nothing else', () => {
    expect(parseHash('#/import')).toEqual({ name: 'import' })
    expect(parseHash(`#/import?token=${TOKEN}`)).toEqual({ name: 'import', token: TOKEN })
    expect(parseHash('#/import?error=address')).toEqual({ name: 'import', error: 'address' })
    expect(parseHash('#/import?token=../../etc')).toEqual({ name: 'import' })
    expect(parseHash(`#/import?token=${TOKEN.toUpperCase()}`)).toEqual({ name: 'import' })
    expect(parseHash('#/import?error=<script>')).toEqual({ name: 'import' })
  })

  it('round-trips through buildHash', () => {
    const routes: Route[] = [
      { name: 'import' },
      { name: 'import', token: TOKEN },
      { name: 'import', error: 'size' },
      { name: 'settings', section: 'bring-in' },
      { name: 'settings' },
    ]
    for (const route of routes) expect(parseHash(buildHash(route))).toEqual(route)
  })

  it('keeps a settings section only when it is a plain word', () => {
    expect(parseHash('#/settings?section=bring-in')).toEqual({ name: 'settings', section: 'bring-in' })
    expect(parseHash('#/settings?section=%3Cb%3E')).toEqual({ name: 'settings' })
  })
})

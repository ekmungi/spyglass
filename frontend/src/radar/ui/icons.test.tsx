// Tests for the icon vocabulary: accessibility defaults of the Icon wrapper, the shared stroke and
// size scale, and that no two meanings share a glyph.
import { render, screen } from '@testing-library/react'
import { Bookmark } from 'lucide-react'
import { describe, expect, it } from 'vitest'
import { ICON_GLYPHS, ICON_STROKE } from './iconGlyphs'
import { Icon, IconFiled, IconFileInVault, IconSaveForLater, IconToday } from './icons'

function svgOf(container: HTMLElement): SVGSVGElement {
  const svg = container.querySelector('svg')
  if (!svg) throw new Error('no svg rendered')
  return svg
}

describe('Icon', () => {
  it('is hidden from screen readers and not focusable by default', () => {
    const { container } = render(<Icon glyph={Bookmark} />)
    const svg = svgOf(container)
    expect(svg).toHaveAttribute('aria-hidden', 'true')
    expect(svg).toHaveAttribute('focusable', 'false')
    expect(svg).not.toHaveAttribute('role')
    expect(svg).not.toHaveAttribute('aria-label')
  })

  it('becomes a labelled image when it carries meaning on its own', () => {
    render(<Icon glyph={Bookmark} label="Saved" />)
    const img = screen.getByRole('img', { name: 'Saved' })
    expect(img).not.toHaveAttribute('aria-hidden')
  })

  it('draws with the shared stroke, the default 16px size and the text colour', () => {
    const svg = svgOf(render(<Icon glyph={Bookmark} />).container)
    expect(svg).toHaveAttribute('stroke-width', String(ICON_STROKE))
    expect(svg).toHaveAttribute('width', '16')
    expect(svg).toHaveAttribute('height', '16')
    expect(svg).toHaveAttribute('stroke', 'currentColor')
    expect(svg).toHaveClass('r-icon')
  })

  it('takes a size from the scale and keeps a caller class', () => {
    const svg = svgOf(render(<IconToday size={18} className="extra" />).container)
    expect(svg).toHaveAttribute('width', '18')
    expect(svg).toHaveClass('r-icon', 'extra', 'lucide-newspaper')
  })
})

describe('icon vocabulary', () => {
  it('gives every meaning its own glyph', () => {
    const glyphs = Object.values(ICON_GLYPHS)
    expect(new Set(glyphs).size).toBe(glyphs.length)
  })

  it('draws filing into the vault differently from saving for later', () => {
    const save = svgOf(render(<IconSaveForLater />).container).getAttribute('class')
    const file = svgOf(render(<IconFileInVault />).container).getAttribute('class')
    const filed = svgOf(render(<IconFiled />).container).getAttribute('class')
    expect(new Set([save, file, filed]).size).toBe(3)
  })
})

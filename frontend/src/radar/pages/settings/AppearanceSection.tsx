// AppearanceSection: theme, reading font, interface font, text size and text width. Every change applies at
// once through the shared appearance store (no Save button) and is remembered on this device; the text
// width applies a moment after the slider is released, so the page does not move while it is dragged.
import './appearance.css'
import { useState } from 'react'
import { DEFAULT_APPEARANCE, READING_FONTS, TEXT_SIZES, UI_FONTS, type ThemeChoice } from '../../appearance/catalog'
import { useAppearance } from '../../hooks/useAppearance'
import { useTheme } from '../../hooks/useTheme'
import { Button, SectionHeading } from '../../ui'
import { FontChoices } from './FontChoices'
import { TextWidthSlider } from './TextWidthSlider'

const THEMES: ReadonlyArray<{ value: ThemeChoice; label: string }> = [
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
  { value: 'system', label: 'Follow system' },
]

/** The "Appearance" group of the Settings page (no props). */
export function AppearanceSection() {
  const { choice, setChoice } = useTheme()
  const { appearance, setReadingFont, setUiFont, setTextSize, setTextWidth, reset } = useAppearance()
  const uiStack = (UI_FONTS.find((font) => font.id === appearance.uiFont) ?? UI_FONTS[0]).stack
  // Bumped by "Reset to defaults" so the slider remounts and drops a width still waiting to apply.
  const [resets, setResets] = useState(0)

  return (
    <section aria-labelledby="settings-appearance" className="rst-section">
      <SectionHeading id="settings-appearance" note="Applies at once · remembered on this device">
        Appearance
      </SectionHeading>

      <fieldset className="rst-fonts">
        <legend className="rst-fonts__legend">Theme</legend>
        <div className="rst-theme">
          {THEMES.map((entry) => (
            <label key={entry.value} className="rst-radio">
              <input type="radio" name="theme" value={entry.value} checked={choice === entry.value} onChange={() => setChoice(entry.value)} />
              <span>{entry.label}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <FontChoices
        legend="Reading font"
        name="reading-font"
        options={READING_FONTS}
        value={appearance.readingFont}
        onChange={setReadingFont}
        defaultId={DEFAULT_APPEARANCE.readingFont}
        inheritedStack={uiStack}
        sampleStyle="reading"
      />

      <FontChoices
        legend="Interface font"
        name="interface-font"
        options={UI_FONTS}
        value={appearance.uiFont}
        onChange={setUiFont}
        defaultId={DEFAULT_APPEARANCE.uiFont}
        inheritedStack={uiStack}
        sampleStyle="interface"
      />

      <fieldset className="rst-fonts">
        <legend className="rst-fonts__legend">Text size</legend>
        <div className="rst-theme">
          {TEXT_SIZES.map((size) => (
            <label key={size.id} className="rst-radio">
              <input type="radio" name="text-size" value={size.id} checked={appearance.textSize === size.id} onChange={() => setTextSize(size.id)} />
              <span>{size.label}</span>
            </label>
          ))}
        </div>
        <p className="r-meta rst-fonts__hint">Scales every size in the interface. Comfortable is the designed size.</p>
      </fieldset>

      <fieldset className="rst-fonts">
        <legend className="rst-fonts__legend">Text width</legend>
        <TextWidthSlider key={resets} value={appearance.textWidth} onCommit={setTextWidth} />
        <p className="r-meta rst-fonts__hint">How wide the centre column is on Today, Feed, the reader and the other pages. It stops growing when the window has no more room.</p>
      </fieldset>

      <div className="rst-reset">
        <Button
          variant="quiet"
          size="sm"
          onClick={() => {
            reset()
            setResets((count) => count + 1)
          }}
        >
          Reset to defaults
        </Button>
      </div>
    </section>
  )
}

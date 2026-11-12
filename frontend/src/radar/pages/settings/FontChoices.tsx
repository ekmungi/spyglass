// FontChoices: a radio list of fonts where each option is shown in its own typeface, with a real
// headline and a line of body text so the choice can be judged by reading, not by a name.
import { useEffect } from 'react'
import { FONT_GROUP_LABELS, FONT_SAMPLE, headingMinWeight, type FontGroup, type FontOption, type ReadingFontId } from '../../appearance/catalog'
import { loadFont } from '../../appearance/appearanceStore'

export interface FontChoicesProps<Id extends string> {
  /** Visible group title, also the accessible name of the radio group. */
  legend: string
  /** Form field name shared by the radios. */
  name: string
  options: ReadonlyArray<FontOption<Id>>
  value: Id
  onChange: (id: Id) => void
  /** The id marked "default". */
  defaultId: Id
  /** The font stack for an option whose own stack is empty (reading font "Sans" follows this). */
  inheritedStack: string
  /** Whether samples are set as reading text (serif headline weight) or as interface text. */
  sampleStyle: 'reading' | 'interface'
}

/** One fieldset of font radios. Opening it fetches every option's font so each previews faithfully. */
export function FontChoices<Id extends string>({ legend, name, options, value, onChange, defaultId, inheritedStack, sampleStyle }: FontChoicesProps<Id>) {
  useEffect(() => {
    options.forEach((option) => void loadFont(option))
  }, [options])

  // Options arrive ordered default, notes theme, more; each group becomes a list under its own small heading.
  const groups = (['default', 'notes', 'more'] as FontGroup[])
    .map((group) => ({ group, items: options.filter((option) => option.group === group) }))
    .filter((entry) => entry.items.length > 0)

  return (
    <fieldset className="rst-fonts">
      <legend className="rst-fonts__legend">{legend}</legend>
      {groups.map(({ group, items }) => (
        <div key={group} role="group" aria-label={FONT_GROUP_LABELS[group] ?? undefined}>
          {FONT_GROUP_LABELS[group] && <p className="rst-fonts__group">{FONT_GROUP_LABELS[group]}</p>}
          <ul className="r-rows">
            {items.map((option) => {
              const family = option.stack || inheritedStack
              return (
                <li key={option.id}>
                  <label className="rst-font">
                    <input type="radio" name={name} value={option.id} aria-label={option.label} checked={value === option.id} onChange={() => onChange(option.id)} />
                    <span className="rst-font__text" style={{ fontFamily: family }}>
                      <span className="rst-font__name">
                        {option.label}
                        {option.id === defaultId && <span className="rst-font__tag"> · default</span>}
                      </span>
                      <span
                        className={`rst-font__headline rst-font__headline--${sampleStyle}`}
                        style={sampleStyle === 'reading' ? { fontWeight: Math.max(500, headingMinWeight(option.id as ReadingFontId)) } : undefined}
                      >{FONT_SAMPLE.headline}</span>
                      <span className="rst-font__body">{FONT_SAMPLE.body}</span>
                    </span>
                  </label>
                </li>
              )
            })}
          </ul>
        </div>
      ))}
    </fieldset>
  )
}

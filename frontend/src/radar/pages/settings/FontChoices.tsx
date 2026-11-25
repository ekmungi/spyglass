// FontChoices: one menu of fonts with a real headline and a line of body text below it, set in the
// chosen font, so the choice can be judged by reading rather than by a name.
import { useEffect } from 'react'
import { FONT_GROUP_LABELS, FONT_SAMPLE, headingMinWeight, type FontGroup, type FontOption, type ReadingFontId } from '../../appearance/catalog'
import { loadFont } from '../../appearance/appearanceStore'
import { Select } from '../../ui'

export interface FontChoicesProps<Id extends string> {
  /** Visible group title, also the accessible name of the menu. */
  legend: string
  options: ReadonlyArray<FontOption<Id>>
  value: Id
  onChange: (id: Id) => void
  /** The id marked "default". */
  defaultId: Id
  /** The font stack for an option whose own stack is empty (reading font "Sans" follows this). */
  inheritedStack: string
  /** Whether the sample is set as reading text (serif headline weight) or as interface text. */
  sampleStyle: 'reading' | 'interface'
}

/** One fieldset: the font menu and the sample of the chosen font. Choosing an entry sets the font at once. */
export function FontChoices<Id extends string>({ legend, options, value, onChange, defaultId, inheritedStack, sampleStyle }: FontChoicesProps<Id>) {
  const chosen = options.find((option) => option.id === value) ?? options[0]

  // The sample shows the chosen font, so its files must be loaded; choosing an entry loads the new one.
  useEffect(() => {
    if (chosen) void loadFont(chosen)
  }, [chosen])

  /** A menu entry: the font's name, marked when it is the default. */
  const entry = (option: FontOption<Id>) => ({ value: option.id, label: option.id === defaultId ? `${option.label} (default)` : option.label })
  // Options arrive ordered default, notes theme, more; the default group has no title and is listed first, plain.
  const grouped = (['notes', 'more'] as FontGroup[])
    .map((group) => ({ label: FONT_GROUP_LABELS[group] ?? '', options: options.filter((option) => option.group === group).map(entry) }))
    .filter((menuGroup) => menuGroup.options.length > 0)
  const plain = options.filter((option) => option.group === 'default').map(entry)

  const family = chosen?.stack || inheritedStack

  return (
    <fieldset className="rst-fonts">
      <legend className="rst-fonts__legend">{legend}</legend>
      <Select label={legend} hideLabel value={chosen?.id ?? ''} onChange={(id) => onChange(id as Id)} options={plain} groups={grouped} className="rst-fonts__menu" />
      <div className="rst-font__sample" style={{ fontFamily: family }}>
        <span
          className={`rst-font__headline rst-font__headline--${sampleStyle}`}
          style={sampleStyle === 'reading' && chosen ? { fontWeight: Math.max(500, headingMinWeight(chosen.id as ReadingFontId)) } : undefined}
        >
          {FONT_SAMPLE.headline}
        </span>
        <span className="rst-font__body">{FONT_SAMPLE.body}</span>
      </div>
    </fieldset>
  )
}

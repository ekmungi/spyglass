// Settings tab: theme picker, font-size + layout sliders, service settings.
import { useState } from 'react'
import {
  applyLayout,
  DEFAULT_LAYOUT,
  loadAppearance,
  saveAppearance,
  type Layout,
} from '../lib/appearance'
import { applyPreset, applySizes, buildPresets, DEFAULT_SIZES, type Sizes } from '../lib/presets'
import { CategorySettingsSection } from './CategorySettingsSection'
import { ServiceSettingsSection } from './ServiceSettingsSection'

const PRESETS = buildPresets()

const SLIDERS: { key: keyof Sizes; label: string; min: number; max: number; step: number }[] = [
  { key: 'headline', label: 'Headline', min: 15, max: 28, step: 0.5 },
  { key: 'body', label: 'Summary text', min: 12, max: 19, step: 0.5 },
  { key: 'meta', label: 'Source label', min: 9, max: 15, step: 0.5 },
  { key: 'actions', label: 'Action row', min: 10, max: 17, step: 0.5 },
  { key: 'lineHeight', label: 'Line height', min: 1.2, max: 1.9, step: 0.05 },
]

const LAYOUT_SLIDERS: { key: keyof Layout; label: string; min: number; max: number; step: number; unit: string }[] = [
  { key: 'maxWidth', label: 'Workspace width', min: 960, max: 2400, step: 20, unit: 'px' },
  { key: 'listWidth', label: 'List pane width', min: 25, max: 60, step: 1, unit: '%' },
]

/** Theme, typography, and layout settings; changes apply live and persist. */
export function SettingsTab() {
  const initial = loadAppearance()
  const [theme, setTheme] = useState(initial.theme)
  const [sizes, setSizes] = useState<Sizes>(initial.sizes)
  const [layout, setLayout] = useState<Layout>(initial.layout)

  const persist = (next: { theme?: string; sizes?: Sizes; layout?: Layout }) => {
    saveAppearance({
      theme: next.theme ?? theme,
      sizes: next.sizes ?? sizes,
      layout: next.layout ?? layout,
    })
  }

  const changeTheme = (name: string) => {
    const preset = PRESETS.find((p) => p.name === name)
    if (preset) {
      applyPreset(preset)
      setTheme(name)
      persist({ theme: name })
    }
  }

  const changeSize = (key: keyof Sizes, value: number) => {
    const next = { ...sizes, [key]: value }
    setSizes(next)
    applySizes(next)
    persist({ sizes: next })
  }

  const changeLayout = (key: keyof Layout, value: number) => {
    const next = { ...layout, [key]: value }
    setLayout(next)
    applyLayout(next)
    persist({ layout: next })
  }

  const reset = () => {
    setSizes(DEFAULT_SIZES)
    applySizes(DEFAULT_SIZES)
    setLayout(DEFAULT_LAYOUT)
    applyLayout(DEFAULT_LAYOUT)
    persist({ sizes: DEFAULT_SIZES, layout: DEFAULT_LAYOUT })
  }

  return (
    // A centered fixed-width card (mockup .settings): the workspace-width
    // slider deliberately does NOT stretch the settings form.
    <div
      className="card-shadow mx-auto max-w-[680px] border border-border bg-card px-6 py-5"
      style={{ fontSize: 'var(--font-size-body)', borderRadius: 'var(--radius-card)' }}
    >
      <h3 className="mb-3 font-semibold text-ink" style={{ fontSize: 'var(--font-size-body)' }}>
        Appearance
      </h3>
      <label className="mb-1 block font-semibold text-ink" htmlFor="theme-select">
        Theme
      </label>
      <select
        id="theme-select"
        className="mb-6 w-full border border-border bg-canvas p-2 text-body"
        style={{ borderRadius: 'var(--radius-control)' }}
        value={theme}
        onChange={(event) => changeTheme(event.target.value)}
      >
        {PRESETS.map((preset) => (
          <option key={preset.name} value={preset.name}>
            {preset.label}
          </option>
        ))}
      </select>

      {SLIDERS.map(({ key, label, min, max, step }) => (
        <div key={key} className="mb-4">
          <label className="mb-1 block font-semibold text-ink" htmlFor={`size-${key}`}>
            {label} <span className="text-accent">{sizes[key]}</span>
          </label>
          <input
            id={`size-${key}`}
            type="range"
            className="w-full"
            min={min}
            max={max}
            step={step}
            value={sizes[key]}
            onChange={(event) => changeSize(key, Number(event.target.value))}
          />
        </div>
      ))}

      <h3
        className="mb-3 mt-5 border-t border-border pt-4 font-semibold text-ink"
        style={{ fontSize: 'var(--font-size-body)' }}
      >
        Layout (workspace panes)
      </h3>
      {LAYOUT_SLIDERS.map(({ key, label, min, max, step, unit }) => (
        <div key={key} className="mb-4">
          <label className="mb-1 block font-semibold text-ink" htmlFor={`layout-${key}`}>
            {label} <span className="text-accent">{layout[key]}{unit}</span>
          </label>
          <input
            id={`layout-${key}`}
            type="range"
            className="w-full"
            min={min}
            max={max}
            step={step}
            value={layout[key]}
            onChange={(event) => changeLayout(key, Number(event.target.value))}
          />
        </div>
      ))}

      <button
        className="bg-accent px-4 py-2 font-semibold text-card"
        style={{ borderRadius: 'var(--radius-control)' }}
        onClick={reset}
      >
        Reset to defaults
      </button>

      <CategorySettingsSection />
      <ServiceSettingsSection />
    </div>
  )
}

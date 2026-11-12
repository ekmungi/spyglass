// Engine choice: which AI engine and model the assistant uses. Remembers the reader's pick and
// falls back to the server's default engine when the pick is no longer available.
import { useCallback } from 'react'
import { getEngines } from '../api/client'
import type { Engine } from '../api/types'
import { useLocalStorage } from '../hooks/useLocalStorage'
import { useResource } from '../hooks/useResource'
import type { SelectGroup } from '../ui'

export interface EngineChoice {
  engine: string
  model: string | null
}

const KEY = 'radar.assist.engine'
const SEPARATOR = '::'

/** The model to use for an engine: its default, else its first model, else none. */
function modelFor(engine: Engine, wanted?: string | null): string | null {
  if (wanted && engine.models.some((model) => model.id === wanted)) return wanted
  return engine.default_model ?? engine.models[0]?.id ?? null
}

/**
 * Resolve the choice to use: the stored pick when its engine is available, else the available
 * engine marked default, else the first available engine; null when none is available.
 */
export function resolveChoice(engines: Engine[], stored: EngineChoice | null): EngineChoice | null {
  const available = engines.filter((engine) => engine.available)
  const storedEngine = stored ? available.find((engine) => engine.id === stored.engine) : undefined
  if (storedEngine) return { engine: storedEngine.id, model: modelFor(storedEngine, stored?.model) }
  const fallback = available.find((engine) => engine.is_default) ?? available[0]
  return fallback ? { engine: fallback.id, model: modelFor(fallback) } : null
}

/** Encode a choice as a single select value. */
export function encodeChoice(choice: EngineChoice | null): string {
  return choice ? `${choice.engine}${SEPARATOR}${choice.model ?? ''}` : ''
}

/** Decode a select value back into a choice. */
export function decodeChoice(value: string): EngineChoice | null {
  if (!value) return null
  const [engine, model] = value.split(SEPARATOR)
  return { engine, model: model || null }
}

/** Option groups for the drop-down: one group per engine; unavailable engines show their reason, disabled. */
export function engineGroups(engines: Engine[]): SelectGroup[] {
  return engines.map((engine) => {
    if (!engine.available) {
      return {
        label: `${engine.label} (not available)`,
        options: [{ value: `unavailable${SEPARATOR}${engine.id}`, label: engine.reason || 'Not set up', disabled: true }],
      }
    }
    const models = engine.models.length ? engine.models : [{ id: '', label: engine.label }]
    return {
      label: engine.label,
      options: models.map((model) => ({ value: `${engine.id}${SEPARATOR}${model.id}`, label: model.label })),
    }
  })
}

/** Engines, the effective choice and a setter, for the assistant header. */
export function useEngineChoice() {
  const engines = useResource('engines', getEngines)
  const [stored, setStored] = useLocalStorage<EngineChoice | null>(KEY, null)
  const list = engines.data ?? []
  const choice = resolveChoice(list, stored)
  const setChoice = useCallback((value: string) => setStored(decodeChoice(value)), [setStored])
  return { engines: list, loading: engines.loading, error: engines.error, reload: engines.reload, choice, setChoice }
}

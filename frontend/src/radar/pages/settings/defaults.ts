// Which engine and model the default selects start on.
import type { EngineRow } from './api'

/** The engine whose model list applies: the saved one if it works, else the service's default, else the first that works. */
export function initialEngine(engines: readonly EngineRow[], savedEngine: string): string {
  const usable = engines.filter((engine) => engine.available)
  return usable.find((engine) => engine.id === savedEngine)?.id ?? usable.find((engine) => engine.is_default)?.id ?? usable[0]?.id ?? ''
}

/** The model to show for an engine: the saved one if the engine offers it, else the engine's own default. */
export function initialModel(engine: EngineRow | undefined, savedModel: string): string {
  if (!engine) return ''
  const ids = engine.models.map((model) => model.id)
  if (savedModel && ids.includes(savedModel)) return savedModel
  return engine.default_model && ids.includes(engine.default_model) ? engine.default_model : (ids[0] ?? '')
}

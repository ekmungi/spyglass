// useTheme: light / dark / system preference. The choice lives in the shared appearance store, so
// every component using this hook (the rail toggle, the Settings control) sees the same value.
import { useCallback, useEffect, useState, useSyncExternalStore } from 'react'
import { getAppearance, setAppearance, subscribeAppearance } from '../appearance/appearanceStore'
import type { ThemeChoice } from '../appearance/catalog'

export type { ThemeChoice }

/** Whether the system currently prefers dark. */
function systemPrefersDark(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(prefers-color-scheme: dark)').matches
}

/** The current choice, the resolved theme, a setter and a light/dark toggle. */
export function useTheme(): { choice: ThemeChoice; resolved: 'light' | 'dark'; setChoice: (choice: ThemeChoice) => void; toggle: () => void } {
  const choice = useSyncExternalStore(subscribeAppearance, () => getAppearance().theme)
  const [systemDark, setSystemDark] = useState(systemPrefersDark)

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const query = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => setSystemDark(query.matches)
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])

  const setChoice = useCallback((next: ThemeChoice) => setAppearance({ theme: next }), [])
  const resolved: 'light' | 'dark' = choice === 'system' ? (systemDark ? 'dark' : 'light') : choice
  const toggle = useCallback(() => setChoice(resolved === 'dark' ? 'light' : 'dark'), [resolved, setChoice])
  return { choice, resolved, setChoice, toggle }
}

// useLocalStorage: a state value persisted in localStorage (JSON), tolerant of blocked storage.
import { useCallback, useState } from 'react'

/** Read a stored JSON value, or `fallback` when missing, corrupt or storage is unavailable. */
export function readStored<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key)
    return raw === null ? fallback : (JSON.parse(raw) as T)
  } catch {
    return fallback
  }
}

/** Write a JSON value; failures (private mode, quota) are ignored because the value is only a preference. */
export function writeStored<T>(key: string, value: T): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* preference only: losing it is harmless */
  }
}

/** State that survives reloads under `key`. */
export function useLocalStorage<T>(key: string, fallback: T): [T, (value: T | ((current: T) => T)) => void] {
  const [value, setValue] = useState<T>(() => readStored(key, fallback))
  const update = useCallback(
    (next: T | ((current: T) => T)) => {
      setValue((current) => {
        const resolved = typeof next === 'function' ? (next as (current: T) => T)(current) : next
        writeStored(key, resolved)
        return resolved
      })
    },
    [key],
  )
  return [value, update]
}

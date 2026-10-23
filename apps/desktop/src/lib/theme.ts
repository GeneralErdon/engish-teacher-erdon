import { useSyncExternalStore } from 'react'

/** What the user picked. `system` follows the OS and changes with it. */
export type ThemePreference = 'system' | 'light' | 'dark'
export type Theme = 'light' | 'dark'

export const THEME_PREFERENCES: readonly ThemePreference[] = ['system', 'light', 'dark']

const STORAGE_KEY = 'voice-tutor:theme'
const DARK_QUERY = '(prefers-color-scheme: dark)'

function isPreference(value: unknown): value is ThemePreference {
  return THEME_PREFERENCES.includes(value as ThemePreference)
}

/** Storage can be unavailable (private windows, blocked site data): fall back to `system`. */
function readPreference(): ThemePreference {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    return isPreference(stored) ? stored : 'system'
  } catch {
    return 'system'
  }
}

function writePreference(preference: ThemePreference) {
  try {
    window.localStorage.setItem(STORAGE_KEY, preference)
  } catch {
    // The choice still applies for this session.
  }
}

function systemTheme(): Theme {
  return window.matchMedia(DARK_QUERY).matches ? 'dark' : 'light'
}

export function resolveTheme(preference: ThemePreference): Theme {
  return preference === 'system' ? systemTheme() : preference
}

interface ThemeState {
  preference: ThemePreference
  theme: Theme
}

let state: ThemeState | undefined
const listeners = new Set<() => void>()

function current(): ThemeState {
  if (!state) {
    const preference = readPreference()
    state = { preference, theme: resolveTheme(preference) }
  }
  return state
}

function update(preference: ThemePreference) {
  const theme = resolveTheme(preference)
  state = { preference, theme }
  const root = document.documentElement
  root.classList.toggle('dark', theme === 'dark')
  root.style.colorScheme = theme
  for (const listener of listeners) listener()
}

/** Applies the saved theme before React renders, so the first paint has the right colours. */
export function initTheme() {
  update(current().preference)
  window.matchMedia(DARK_QUERY).addEventListener('change', () => {
    if (current().preference === 'system') update('system')
  })
}

export function setThemePreference(preference: ThemePreference) {
  writePreference(preference)
  update(preference)
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function useTheme(): ThemeState & { setPreference: (p: ThemePreference) => void } {
  const snapshot = useSyncExternalStore(subscribe, current)
  return { ...snapshot, setPreference: setThemePreference }
}

import { useCallback, useState } from 'react'

const STORAGE_KEY = 'voice-tutor:voice-replies'

/** Storage can be unavailable (private windows, blocked site data): the voice stays on. */
function readPreference(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) !== 'off'
  } catch {
    return true
  }
}

/** Whether the tutor reads its replies aloud. On by default; remembered on this device. */
export function useVoiceReplies() {
  const [on, setOn] = useState(readPreference)
  const set = useCallback((next: boolean) => {
    setOn(next)
    try {
      window.localStorage.setItem(STORAGE_KEY, next ? 'on' : 'off')
    } catch {
      // The choice still applies until the page is closed.
    }
  }, [])
  return [on, set] as const
}

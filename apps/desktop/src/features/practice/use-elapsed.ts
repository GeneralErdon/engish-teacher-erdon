import { useEffect, useState } from 'react'

/** Whole seconds since the component mounted, updated four times a second. */
export function useElapsedSeconds() {
  const [seconds, setSeconds] = useState(0)

  useEffect(() => {
    const started = Date.now()
    const timer = setInterval(() => {
      setSeconds(Math.floor((Date.now() - started) / 1000))
    }, 250)
    return () => {
      clearInterval(timer)
    }
  }, [])

  return seconds
}

/** 75 → "1:15". */
export function clock(seconds: number) {
  return `${String(Math.floor(seconds / 60))}:${String(seconds % 60).padStart(2, '0')}`
}

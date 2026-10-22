import { useCallback, useEffect, useRef, useState } from 'react'

import { level, microphoneError, type AudioSource } from '@/lib/audio/source'
import { createWebAudioSource } from '@/lib/audio/web-audio-source'

const LEVEL_EVERY_FRAMES = 5 // a meter update every 100 ms is smooth enough, and cheap

export type RecorderState = 'idle' | 'starting' | 'recording'

/** Push-to-talk recording: frames go to `onFrame` while recording. */
export function useRecorder(onFrame: (pcm: ArrayBuffer) => void) {
  const [state, setState] = useState<RecorderState>('idle')
  const [error, setError] = useState<string>()
  const [meter, setMeter] = useState(0)
  const source = useRef<AudioSource | null>(null)
  const frameHandler = useRef(onFrame)

  useEffect(() => {
    frameHandler.current = onFrame
  }, [onFrame])

  const stop = useCallback(async () => {
    const current = source.current
    source.current = null
    setState('idle')
    setMeter(0)
    await current?.stop()
  }, [])

  const start = useCallback(async () => {
    setError(undefined)
    setState('starting')
    const next = createWebAudioSource()
    source.current = next
    let frames = 0
    try {
      await next.start((pcm) => {
        frameHandler.current(pcm)
        if (++frames % LEVEL_EVERY_FRAMES === 0) setMeter(level(pcm))
      })
      setState('recording')
    } catch (failure) {
      source.current = null
      setState('idle')
      setError(microphoneError(failure))
    }
  }, [])

  // Never leave the microphone on after leaving the page.
  useEffect(
    () => () => {
      void source.current?.stop()
    },
    [],
  )

  return { state, error, meter, start, stop }
}

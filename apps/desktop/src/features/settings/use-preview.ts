import { queryOptions, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'

import { fetchClient, type Schemas } from '@/lib/api/client'
import { errorMessage } from '@/lib/api/errors'

type VoicePreview = Schemas['VoicePreview']

/** How long a sample heard stays at hand: trying voices back and forth replays them at once. */
const SAMPLE_KEPT_MS = 30 * 60_000

/** The sample sentence in a voice, at a speed: one per combination, synthesized once. */
const sampleQuery = (body: VoicePreview) =>
  queryOptions({
    queryKey: ['voice-preview', body.model, body.voice, body.speed],
    queryFn: async ({ signal }) => {
      const { data } = await fetchClient.POST('/v1/speech/preview', {
        body,
        parseAs: 'blob',
        signal,
      })
      return data as Blob
    },
    staleTime: Infinity,
    gcTime: SAMPLE_KEPT_MS,
  })

/**
 * Plays `sample` through the browser until it ends or `signal` aborts; either way, its object URL
 * is released. `onStart` runs once the sound starts, unless aborted before.
 */
async function play(sample: Blob, signal: AbortSignal, onStart: () => void): Promise<void> {
  const url = URL.createObjectURL(sample)
  const audio = new Audio(url)
  try {
    const over = new Promise<void>((resolve) => {
      audio.addEventListener('ended', () => {
        resolve()
      })
      signal.addEventListener('abort', () => {
        audio.pause()
        resolve()
      })
    })
    await audio.play()
    if (!signal.aborted) onStart()
    await over
  } finally {
    URL.revokeObjectURL(url)
  }
}

interface PreviewState {
  /** The voice whose sample is loading or playing. */
  voice: string
  playing: boolean
}

/**
 * Voice samples, one at a time like a single speaker: starting one stops the one before (its
 * request too, when it has not come back), and toggling the voice in progress stops it.
 */
export function usePreview() {
  const queryClient = useQueryClient()
  const [current, setCurrent] = useState<PreviewState>()
  const [error, setError] = useState<string>()
  /** Aborting it ends the preview in progress, wherever it is. */
  const inProgress = useRef<AbortController | null>(null)

  // Never leave a sample playing after leaving the page.
  useEffect(
    () => () => {
      inProgress.current?.abort()
      inProgress.current = null
    },
    [],
  )

  const toggle = useCallback(
    (request: VoicePreview) => {
      const again = current?.voice === request.voice
      inProgress.current?.abort()
      inProgress.current = null
      setError(undefined)
      if (again) {
        setCurrent(undefined)
        return
      }

      const preview = new AbortController()
      inProgress.current = preview
      const { signal } = preview
      const sample = sampleQuery(request)
      signal.addEventListener('abort', () => {
        void queryClient.cancelQueries({ queryKey: sample.queryKey, exact: true })
      })
      setCurrent({ voice: request.voice, playing: false })

      void (async () => {
        try {
          const audio = await queryClient.query(sample)
          if (signal.aborted) return
          await play(audio, signal, () => {
            setCurrent({ voice: request.voice, playing: true })
          })
        } catch (failure) {
          if (!signal.aborted) setError(errorMessage(failure))
        } finally {
          if (inProgress.current === preview) {
            inProgress.current = null
            setCurrent(undefined)
          }
        }
      })()
    },
    [current, queryClient],
  )

  return { current, error, toggle }
}

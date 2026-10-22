import { useCallback, useEffect, useRef, useState } from 'react'

import { microphoneError } from '@/lib/audio/source'
import { createVoiceDetector, type VoiceDetector } from '@/lib/audio/vad'

import type { Turn } from './use-conversation'

export type CallPhase = 'starting' | 'listening' | 'hearing' | 'thinking' | 'speaking'

/** What a call needs from the conversation (`useConversation`). */
export interface CallConversation {
  turns: Turn[]
  replying: boolean
  speaking: boolean
  transcribing: boolean
  interrupt: () => void
  sendAudio: (pcm: ArrayBuffer) => void
  commit: () => void
}

/**
 * Hands-free turns: the voice detector listens all along, sends each utterance when the learner
 * stops talking, and interrupts the tutor when the learner talks over it.
 */
export function useCall(conversation: CallConversation) {
  const [ready, setReady] = useState(false)
  const [hearing, setHearing] = useState(false)
  const [muted, setMuted] = useState(false)
  const [error, setError] = useState<string>()
  const detector = useRef<VoiceDetector | null>(null)
  const micLevel = useRef(0)
  // The detector's callbacks outlive renders: they read the conversation through this ref.
  const latest = useRef(conversation)

  useEffect(() => {
    latest.current = conversation
  })

  useEffect(() => {
    let cancelled = false
    let created: VoiceDetector | undefined
    const tutorBusy = () => latest.current.replying || latest.current.speaking

    createVoiceDetector({
      onSpeechStart: () => {
        // Over the tutor, wait until the speech is confirmed: it may be the tutor's own echo.
        if (!tutorBusy()) setHearing(true)
      },
      onSpeechConfirmed: () => {
        // Talking over the tutor interrupts it, like in a real conversation.
        if (tutorBusy()) latest.current.interrupt()
        setHearing(true)
      },
      onSpeechEnd: (frames) => {
        for (const frame of frames) latest.current.sendAudio(frame)
        latest.current.commit()
        setHearing(false)
      },
      onMisfire: () => {
        setHearing(false)
      },
      onLevel: (level) => {
        micLevel.current = level
      },
    })
      .then(async (voice) => {
        if (cancelled) {
          await voice.destroy()
          return
        }
        created = voice
        detector.current = voice
        await voice.start()
        setReady(true)
      })
      .catch((failure: unknown) => {
        if (!cancelled) setError(microphoneError(failure))
      })

    return () => {
      cancelled = true
      detector.current = null
      void created?.destroy()
    }
  }, [])

  // While the tutor talks, its voice can reach the microphone: only clear speech counts.
  useEffect(() => {
    detector.current?.setStrict(conversation.speaking)
  }, [conversation.speaking, ready])

  const toggleMute = useCallback(async () => {
    const voice = detector.current
    if (!voice) return
    if (muted) await voice.start()
    else await voice.pause()
    micLevel.current = 0
    setHearing(false)
    setMuted(!muted)
  }, [muted])

  const last = conversation.turns.at(-1)
  const awaitingReply = last !== undefined && !last.metrics && !last.error && !last.interrupted
  const phase: CallPhase = !ready
    ? 'starting'
    : hearing
      ? 'hearing'
      : conversation.speaking
        ? 'speaking'
        : conversation.transcribing || awaitingReply
          ? 'thinking'
          : 'listening'

  const micLevelNow = useCallback(() => micLevel.current, [])

  return { phase, error, muted, toggleMute, micLevel: micLevelNow }
}

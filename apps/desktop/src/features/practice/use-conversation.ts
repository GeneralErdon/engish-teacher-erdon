import { useCallback, useEffect, useReducer, useRef, useState } from 'react'

import type { Schemas } from '@/lib/api/client'
import { createVoicePlayer, type VoicePlayer } from '@/lib/audio/player'
import { backendUrl } from '@/lib/platform'

export type ServerEvent = Schemas['ServerEvent']
export type ClientEvent = Schemas['ClientEvent']
export type Correction = Schemas['Correction']
export type TurnMetrics = Schemas['TurnMetrics']

export interface Turn {
  id: string
  text: string
  source: 'text' | 'voice'
  /** Speech-to-text time, for spoken turns. */
  sttMs: number | null
  /** The spoken turn went over the longest-turn setting and was transcribed up to it. */
  cut: boolean
  reply: string
  replyDone: boolean
  interrupted: boolean
  correction?: Correction
  metrics?: TurnMetrics
  error?: string | undefined
}

export interface ConversationState {
  status: 'connecting' | 'open' | 'closed'
  session?: Schemas['SessionReady']
  turns: Turn[]
  /** The turn whose reply was last spoken aloud. */
  voiceTurn?: string
  /** Spoken audio was sent and its transcript has not come back yet. */
  transcribing: boolean
  error?: string | undefined
  /**
   * The chosen speech engine cannot transcribe, so Speaches does (`speech_engine_unavailable`).
   * Unlike `error`, it stays for the rest of the conversation: later turns and errors keep it.
   */
  notice?: string | undefined
}

type Action =
  { type: 'status'; status: ConversationState['status'] } | { type: 'transcribing' } | ServerEvent

/**
 * Errors that end a transcription without a turn. `audio_too_long` is gone from the api (long
 * turns are cut now), but a v0.1.0 api still sends it: keep it for one release, or this UI would
 * stay "transcribing" against that api.
 */
const SPEECH_ERRORS = new Set<string>([
  'stt_failed',
  'no_speech',
  'audio_too_short',
  'audio_too_long',
  'not_started',
])

const initial: ConversationState = { status: 'connecting', turns: [], transcribing: false }

function updateTurn(state: ConversationState, id: string, change: (turn: Turn) => Turn) {
  return { ...state, turns: state.turns.map((turn) => (turn.id === id ? change(turn) : turn)) }
}

export function reducer(state: ConversationState, action: Action): ConversationState {
  switch (action.type) {
    case 'status':
      return { ...state, status: action.status }
    case 'transcribing':
      return { ...state, transcribing: true }
    case 'session.ready':
      return { ...state, session: action, error: undefined, notice: undefined }
    case 'transcript.final':
      return {
        ...state,
        // A new turn made it through: earlier problems (a failed recording, say) are over.
        error: undefined,
        transcribing: false,
        turns: [
          ...state.turns,
          {
            id: action.turn_id,
            text: action.text,
            source: action.source,
            sttMs: action.stt_ms,
            cut: action.cut,
            reply: '',
            replyDone: false,
            interrupted: false,
          },
        ],
      }
    case 'assistant.text.delta':
      return updateTurn(state, action.turn_id, (turn) => ({
        ...turn,
        reply: turn.reply + action.text,
      }))
    case 'assistant.text.done':
      return updateTurn(state, action.turn_id, (turn) => ({
        ...turn,
        reply: action.text,
        replyDone: true,
        interrupted: action.interrupted,
      }))
    case 'assistant.audio.started':
      return { ...state, voiceTurn: action.turn_id }
    case 'assistant.audio.done':
      // The audio itself was handled as it arrived (binary frames, see `useConversation`).
      return state
    case 'correction':
      return updateTurn(state, action.turn_id, (turn) => ({ ...turn, correction: action }))
    case 'turn.metrics':
      return updateTurn(state, action.turn_id, (turn) => ({ ...turn, metrics: action }))
    case 'error': {
      // Transcription goes on with Speaches: a notice, not an error, and not a speech error.
      if (action.code === 'speech_engine_unavailable') return { ...state, notice: action.message }
      // A failed reply belongs to the turn in progress; anything else is about the session.
      const last = state.turns.at(-1)
      if (action.code === 'llm_failed' && last && !last.replyDone) {
        return updateTurn(state, last.id, (turn) => ({
          ...turn,
          replyDone: true,
          error: action.message,
        }))
      }
      return {
        ...state,
        error: action.message,
        transcribing: state.transcribing && !SPEECH_ERRORS.has(action.code),
      }
    }
  }
}

/** `http://host:8080` → `ws://host:8080/ws/session` (and https → wss). */
export function sessionUrl(base: string) {
  return `${base.replace(/^http/, 'ws')}/ws/session`
}

export interface ConversationOptions {
  /** The tutor reads its replies aloud. Can change during the conversation. */
  speak?: boolean
  url?: string
}

/**
 * One conversation over `/ws/session`: connects, starts the session, folds the server's events
 * into turns and plays the tutor's voice. `reconnect` opens a fresh conversation.
 */
export function useConversation({
  speak = false,
  url = sessionUrl(backendUrl()),
}: ConversationOptions = {}) {
  const [state, dispatch] = useReducer(reducer, initial)
  const socket = useRef<WebSocket | null>(null)
  const started = useRef(false)
  const [attempt, nextAttempt] = useReducer((n: number) => n + 1, 0)

  const [speaking, setSpeaking] = useState(false)
  const speakRef = useRef(speak)
  const player = useRef<VoicePlayer | null>(null)
  /** Binary frames play while this is set: between `assistant.audio.started` and `.done`. */
  const voice = useRef<{ turnId: string; sampleRate: number } | null>(null)
  const lastTurn = useRef<string | null>(null)
  /** A turn the learner interrupted: its audio may still be on the way, and must not play. */
  const muted = useRef<string | null>(null)

  const getPlayer = useCallback(() => (player.current ??= createVoicePlayer(setSpeaking)), [])

  const send = useCallback((event: ClientEvent) => {
    socket.current?.send(JSON.stringify(event))
  }, [])

  /** Stop the tutor's voice now, including audio of this turn still on its way. */
  const silence = useCallback(() => {
    muted.current = lastTurn.current
    voice.current = null
    player.current?.stop()
  }, [])

  useEffect(() => {
    dispatch({ type: 'status', status: 'connecting' })
    const ws = new WebSocket(url)
    ws.binaryType = 'arraybuffer'
    socket.current = ws
    ws.onopen = () => {
      dispatch({ type: 'status', status: 'open' })
      ws.send(JSON.stringify({ type: 'session.start', v: 1, topic: null, speak: speakRef.current }))
      started.current = true
    }
    ws.onmessage = (message: MessageEvent<string | ArrayBuffer>) => {
      if (typeof message.data !== 'string') {
        if (voice.current) getPlayer().play(message.data, voice.current.sampleRate)
        return
      }
      const event = JSON.parse(message.data) as ServerEvent
      if (event.type === 'transcript.final') lastTurn.current = event.turn_id
      if (event.type === 'assistant.audio.started' && event.turn_id !== muted.current) {
        voice.current = { turnId: event.turn_id, sampleRate: event.sample_rate }
      }
      if (event.type === 'assistant.audio.done') voice.current = null
      dispatch(event)
    }
    ws.onclose = () => {
      started.current = false
      dispatch({ type: 'status', status: 'closed' })
    }
    return () => {
      started.current = false
      ws.onclose = null
      ws.close()
    }
  }, [url, attempt, getPlayer])

  // Voice on or off during the conversation: the server applies it from the next reply, and
  // the reply playing now stops at once.
  useEffect(() => {
    if (speakRef.current === speak) return
    speakRef.current = speak
    if (!speak) silence()
    if (started.current) send({ type: 'session.update', v: 1, speak })
  }, [speak, send, silence])

  // Never leave audio playing after leaving the page.
  useEffect(
    () => () => {
      void player.current?.close()
    },
    [],
  )

  /** Playing audio needs a user gesture first: call from a click or key handler. */
  const unlockAudio = useCallback(() => {
    getPlayer().unlock()
  }, [getPlayer])

  /** Loudness of the tutor's voice right now, 0..1. */
  const outputLevel = useCallback(() => player.current?.level() ?? 0, [])

  /** Microphone audio for the turn being recorded (binary frames). */
  const sendAudio = useCallback((pcm: ArrayBuffer) => {
    socket.current?.send(pcm)
  }, [])

  const last = state.turns.at(-1)
  return {
    ...state,
    replying: last !== undefined && !last.replyDone,
    /** The tutor's voice is playing. */
    speaking,
    say: (text: string) => {
      // A new message interrupts the reply, on the server and in the speakers.
      silence()
      if (speakRef.current) unlockAudio()
      send({ type: 'input.text', v: 1, text })
    },
    interrupt: () => {
      silence()
      send({ type: 'input.interrupt', v: 1 })
    },
    unlockAudio,
    outputLevel,
    sendAudio,
    /** The learner stopped speaking: transcribe and answer. */
    commit: () => {
      dispatch({ type: 'transcribing' })
      send({ type: 'input.commit', v: 1 })
    },
    reconnect: nextAttempt,
  }
}

export type Conversation = ReturnType<typeof useConversation>

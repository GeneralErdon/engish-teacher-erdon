import { useCallback, useEffect, useReducer, useRef } from 'react'

import type { Schemas } from '@/lib/api/client'
import { backendUrl } from '@/lib/platform'

export type ServerEvent = Schemas['ServerEvent']
export type ClientEvent = Schemas['ClientEvent']
export type Correction = Schemas['Correction']
export type TurnMetrics = Schemas['TurnMetrics']

export interface Turn {
  id: string
  text: string
  source: 'text' | 'voice'
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
  error?: string | undefined
}

type Action = { type: 'status'; status: ConversationState['status'] } | ServerEvent

const initial: ConversationState = { status: 'connecting', turns: [] }

function updateTurn(state: ConversationState, id: string, change: (turn: Turn) => Turn) {
  return { ...state, turns: state.turns.map((turn) => (turn.id === id ? change(turn) : turn)) }
}

export function reducer(state: ConversationState, action: Action): ConversationState {
  switch (action.type) {
    case 'status':
      return { ...state, status: action.status }
    case 'session.ready':
      return { ...state, session: action, error: undefined }
    case 'transcript.final':
      return {
        ...state,
        turns: [
          ...state.turns,
          {
            id: action.turn_id,
            text: action.text,
            source: action.source,
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
    case 'correction':
      return updateTurn(state, action.turn_id, (turn) => ({ ...turn, correction: action }))
    case 'turn.metrics':
      return updateTurn(state, action.turn_id, (turn) => ({ ...turn, metrics: action }))
    case 'error': {
      // A failed reply belongs to the turn in progress; anything else is about the session.
      const last = state.turns.at(-1)
      if (action.code === 'llm_failed' && last && !last.replyDone) {
        return updateTurn(state, last.id, (turn) => ({
          ...turn,
          replyDone: true,
          error: action.message,
        }))
      }
      return { ...state, error: action.message }
    }
  }
}

/** `http://host:8080` → `ws://host:8080/ws/session` (and https → wss). */
export function sessionUrl(base: string) {
  return `${base.replace(/^http/, 'ws')}/ws/session`
}

/**
 * One conversation over `/ws/session`: connects, starts the session, and folds the server's
 * events into turns. `reconnect` opens a fresh conversation.
 */
export function useConversation(url = sessionUrl(backendUrl())) {
  const [state, dispatch] = useReducer(reducer, initial)
  const socket = useRef<WebSocket | null>(null)
  const [attempt, nextAttempt] = useReducer((n: number) => n + 1, 0)

  useEffect(() => {
    dispatch({ type: 'status', status: 'connecting' })
    const ws = new WebSocket(url)
    socket.current = ws
    const send = (event: ClientEvent) => {
      ws.send(JSON.stringify(event))
    }
    ws.onopen = () => {
      dispatch({ type: 'status', status: 'open' })
      send({ type: 'session.start', v: 1, topic: null })
    }
    ws.onmessage = (message: MessageEvent<string>) => {
      dispatch(JSON.parse(message.data) as ServerEvent)
    }
    ws.onclose = () => {
      dispatch({ type: 'status', status: 'closed' })
    }
    return () => {
      ws.onclose = null
      ws.close()
    }
  }, [url, attempt])

  const send = useCallback((event: ClientEvent) => {
    socket.current?.send(JSON.stringify(event))
  }, [])

  const last = state.turns.at(-1)
  return {
    ...state,
    replying: last !== undefined && !last.replyDone,
    say: (text: string) => {
      send({ type: 'input.text', v: 1, text })
    },
    interrupt: () => {
      send({ type: 'input.interrupt', v: 1 })
    },
    reconnect: nextAttempt,
  }
}

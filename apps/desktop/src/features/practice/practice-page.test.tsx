import { screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { FakeSocket, installFakeSocket } from '@/test/fake-socket'
import { renderApp } from '@/test/render-app'

import { reducer, sessionUrl } from './use-conversation'

vi.mock('@/lib/audio/player', async () => {
  const { FakePlayer } = await import('@/test/fake-audio')
  return {
    createVoicePlayer: (onPlayingChange: (playing: boolean) => void) =>
      new FakePlayer(onPlayingChange),
  }
})

const READY = {
  type: 'session.ready',
  v: 1,
  level: 'B1',
  provider: 'Ollama Cloud',
  model: 'gpt-oss:120b',
} as const

const turn = (text = 'Yesterday I have went to the beach') =>
  ({
    type: 'transcript.final',
    v: 1,
    turn_id: 't1',
    text,
    source: 'text',
    stt_ms: null,
    cut: false,
  }) as const

async function openPractice() {
  const view = renderApp('/practice')
  await screen.findByRole('heading', { name: 'Practice' })
  const socket = FakeSocket.last
  socket.open()
  socket.emit(READY)
  return { ...view, socket }
}

beforeEach(() => {
  installFakeSocket()
})

describe('Practice', () => {
  it('connects to the session socket and starts a conversation', async () => {
    const { socket } = await openPractice()

    expect(socket.url).toBe(`${window.location.origin.replace('http', 'ws')}/ws/session`)
    expect(socket.sent).toEqual([{ type: 'session.start', v: 1, topic: null, speak: true }])
    expect(screen.getByText('Level B1')).toBeInTheDocument()
    expect(screen.getByText('Ollama Cloud · gpt-oss:120b')).toBeInTheDocument()
  })

  it('sends a message, streams the reply and marks the mistakes', async () => {
    const { socket, user } = await openPractice()

    await user.type(screen.getByLabelText('Message'), 'Yesterday I have went to the beach{Enter}')
    expect(socket.sent.at(-1)).toEqual({
      type: 'input.text',
      v: 1,
      text: 'Yesterday I have went to the beach',
    })

    socket.emit(turn(), { type: 'assistant.text.delta', v: 1, turn_id: 't1', text: 'Nice!' })
    expect(screen.getByText('Checking your English…')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Stop' }))
    expect(socket.sent.at(-1)).toEqual({ type: 'input.interrupt', v: 1 })

    socket.emit(
      { type: 'assistant.text.delta', v: 1, turn_id: 't1', text: ' What did you do?' },
      {
        type: 'assistant.text.done',
        v: 1,
        turn_id: 't1',
        text: 'Nice! What did you do?',
        interrupted: false,
      },
      {
        type: 'turn.metrics',
        v: 1,
        turn_id: 't1',
        first_token_ms: 820,
        reply_ms: 2140,
        first_audio_ms: null,
      },
      {
        type: 'correction',
        v: 1,
        turn_id: 't1',
        corrected: 'Yesterday I went to the beach',
        latency_ms: 1500,
        items: [
          {
            original: 'have went',
            suggestion: 'went',
            kind: 'grammar',
            explanation: 'Pasado simple: "went".',
          },
        ],
      },
    )

    const conversation = screen.getByRole('list', { name: 'Conversation' })
    expect(within(conversation).getByText('Nice! What did you do?')).toBeInTheDocument()
    expect(within(conversation).getByText('first word 0.8 s · reply 2.1 s')).toBeInTheDocument()
    const correction = screen.getByLabelText('Correction')
    expect(within(correction).getByText('have')).toHaveClass('line-through')
    expect(within(correction).getByText('have went → went')).toBeInTheDocument()
    expect(within(correction).getByText('Pasado simple: "went".')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
  })

  it('says when a message has no mistakes, and shows interruptions and spoken turns', async () => {
    const { socket } = await openPractice()

    socket.emit(
      { ...turn('I went to the beach'), source: 'voice', stt_ms: 640 },
      { type: 'assistant.text.done', v: 1, turn_id: 't1', text: 'Nice', interrupted: true },
      {
        type: 'turn.metrics',
        v: 1,
        turn_id: 't1',
        first_token_ms: null,
        reply_ms: 300,
        first_audio_ms: null,
      },
      {
        type: 'correction',
        v: 1,
        turn_id: 't1',
        corrected: 'I went to the beach',
        items: [],
        latency_ms: 900,
      },
    )

    expect(screen.getByText('Looks good')).toBeInTheDocument()
    expect(screen.getByText('Interrupted')).toBeInTheDocument()
    expect(screen.getByLabelText('Spoken')).toBeInTheDocument()
    expect(screen.getByText('heard 0.6 s · reply 0.3 s')).toBeInTheDocument()
  })

  it('shows a failed reply on its turn, and other errors above', async () => {
    const { socket } = await openPractice()

    socket.emit(turn(), {
      type: 'error',
      v: 1,
      code: 'llm_failed',
      message: 'The provider rejected the API key (HTTP 401).',
      retryable: true,
    })
    expect(screen.getByText('The provider rejected the API key (HTTP 401).')).toBeInTheDocument()

    socket.emit({ type: 'error', v: 1, code: 'bad_event', message: 'Bad event.', retryable: false })
    expect(screen.getByText('Bad event.')).toBeInTheDocument()
  })

  it('sends with the button too, and corrects messages with missing words', async () => {
    const { socket, user } = await openPractice()

    await user.type(screen.getByLabelText('Message'), 'I went beach')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    expect(socket.sent.at(-1)).toEqual({ type: 'input.text', v: 1, text: 'I went beach' })

    socket.emit(turn('Hello'), { ...turn('I went beach'), turn_id: 't2' })
    socket.emit({
      type: 'correction',
      v: 1,
      turn_id: 't2',
      corrected: 'I went to the beach',
      latency_ms: 700,
      items: [
        {
          original: 'beach',
          suggestion: 'to the beach',
          kind: 'grammar',
          explanation: 'Go to a place.',
        },
      ],
    })

    const correction = screen.getByLabelText('Correction')
    expect(within(correction).getByText('to the')).toHaveClass('text-success')
    expect(screen.getAllByText('Checking your English…')).toHaveLength(1)
  })

  it('offers conversation starters', async () => {
    const { socket, user } = await openPractice()

    await user.click(screen.getByRole('button', { name: /job interview/ }))

    expect(socket.sent.at(-1)).toEqual({
      type: 'input.text',
      v: 1,
      text: 'Can you help me prepare for a job interview?',
    })
  })

  it('keeps Shift+Enter for new lines and ignores empty messages', async () => {
    const { socket, user } = await openPractice()
    const box = screen.getByLabelText('Message')

    await user.type(box, '   {Enter}')
    await user.type(box, 'Line one{Shift>}{Enter}{/Shift}line two')

    expect(socket.sent).toHaveLength(1)
    expect(box).toHaveValue('   Line one\nline two')
  })

  it('waits for the session before letting the learner write', async () => {
    renderApp('/practice')

    expect(await screen.findByPlaceholderText('Connecting…')).toBeDisabled()
  })

  it('in the app, says where to point it at another computer', async () => {
    vi.stubGlobal('isTauri', true)
    const { socket } = await openPractice()

    socket.drop()

    expect(screen.getByRole('link', { name: 'Settings → Backend' })).toHaveAttribute(
      'href',
      '/settings',
    )
  })

  it('reconnects after losing the backend', async () => {
    const { socket, user } = await openPractice()

    socket.drop()
    expect(screen.getByText('Disconnected from the tutor')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /reconnect/i }))

    expect(FakeSocket.instances).toHaveLength(2)
    expect(socket.closed).toBe(true)
  })

  it('is reachable from the navigation and from Home', async () => {
    const { user } = renderApp('/')

    await user.click(await screen.findByRole('link', { name: /start a conversation/i }))

    expect(await screen.findByRole('heading', { name: 'Practice' })).toBeInTheDocument()
  })
})

describe('conversation state', () => {
  it('ignores events for turns it does not know', () => {
    const state = { status: 'open' as const, turns: [], transcribing: false }

    expect(
      reducer(state, { type: 'assistant.text.delta', v: 1, turn_id: 'tx', text: 'x' }),
    ).toEqual(state)
  })

  it('builds the socket URL from the backend URL', () => {
    expect(sessionUrl('https://tutor.example')).toBe('wss://tutor.example/ws/session')
  })
})

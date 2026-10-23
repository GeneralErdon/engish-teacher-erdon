import { act, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ServerEvent } from '@/features/practice/use-conversation'
import { fakeApi, type FakeApi } from '@/test/fake-api'
import { FakeMicrophone, FakePlayer } from '@/test/fake-audio'
import { FakeSocket, installFakeSocket } from '@/test/fake-socket'
import { renderApp } from '@/test/render-app'

vi.mock('@/lib/audio/web-audio-source', async () => {
  const { FakeMicrophone: Microphone } = await import('@/test/fake-audio')
  return { createWebAudioSource: () => new Microphone() }
})

vi.mock('@/lib/audio/player', async () => {
  const { FakePlayer: Player } = await import('@/test/fake-audio')
  return {
    createVoicePlayer: (onPlayingChange: (playing: boolean) => void) => new Player(onPlayingChange),
  }
})

async function openPractice(api?: FakeApi) {
  const view = renderApp('/practice', api)
  await screen.findByRole('heading', { name: 'Practice' })
  const socket = FakeSocket.last
  socket.open()
  socket.emit({ type: 'session.ready', v: 1, level: 'B1', provider: 'Ollama Cloud', model: 'm' })
  return { ...view, socket }
}

beforeEach(() => {
  installFakeSocket()
  FakeMicrophone.reset()
  FakePlayer.reset()
})

describe('Speaking', () => {
  it('streams the microphone while recording, then asks for a transcription', async () => {
    const { socket, user } = await openPractice()

    await user.click(screen.getByRole('button', { name: 'Speak' }))
    expect(await screen.findByText(/Listening…/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Message')).not.toBeInTheDocument()

    FakeMicrophone.current?.speak(25)
    expect(socket.audio).toHaveLength(25)
    expect(socket.audio[0]?.byteLength).toBe(640)

    await user.click(screen.getByRole('button', { name: 'Stop and send' }))

    expect(socket.sent.at(-1)).toEqual({ type: 'input.commit', v: 1 })
    expect(FakeMicrophone.current?.recording).toBe(false)
    expect(screen.getByLabelText('Message')).toBeInTheDocument()
  })

  it('interrupts the tutor when the learner starts speaking', async () => {
    const { socket, user } = await openPractice()
    socket.emit(
      { type: 'transcript.final', v: 1, turn_id: 't1', text: 'Hi', source: 'text', stt_ms: null },
      { type: 'assistant.text.delta', v: 1, turn_id: 't1', text: 'Hello' },
    )

    await user.click(screen.getByRole('button', { name: 'Speak' }))

    expect(socket.sent.at(-1)).toEqual({ type: 'input.interrupt', v: 1 })
  })

  it('explains microphone problems', async () => {
    FakeMicrophone.failWith = new DOMException('denied', 'NotAllowedError')
    const { user } = await openPractice()

    await user.click(screen.getByRole('button', { name: 'Speak' }))

    expect(await screen.findByText(/Microphone access was denied/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Speak' })).toBeEnabled()
  })

  it('shows speech recognition errors until the next turn', async () => {
    const { socket } = await openPractice()

    socket.emit({
      type: 'error',
      v: 1,
      code: 'no_speech',
      message: 'I did not catch that. Try again, closer to the mic.',
      retryable: true,
    })
    expect(screen.getByText(/I did not catch that/)).toBeInTheDocument()

    socket.emit({
      type: 'transcript.final',
      v: 1,
      turn_id: 't1',
      text: 'Hello',
      source: 'voice',
      stt_ms: 500,
    })
    expect(screen.queryByText(/I did not catch that/)).not.toBeInTheDocument()
  })

  it('counts the recording time', async () => {
    const { user } = await openPractice()
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      await user.click(screen.getByRole('button', { name: 'Speak' }))
      await act(() => vi.advanceTimersByTimeAsync(2_100))

      expect(screen.getByText('Listening… 0:02')).toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })

  it('turns the microphone off when leaving the page', async () => {
    const { user, router } = await openPractice()
    await user.click(screen.getByRole('button', { name: 'Speak' }))
    await screen.findByText(/Listening…/)

    await router.navigate({ to: '/' })

    expect(await screen.findByRole('heading', { name: /speak english/i })).toBeInTheDocument()
    expect(FakeMicrophone.current?.recording).toBe(false)
  })
})

const pcm = (samples = 2_400) => new Int16Array(samples).buffer

const spokenTurn = (id = 't1'): ServerEvent[] => [
  { type: 'transcript.final', v: 1, turn_id: id, text: 'Hi', source: 'text', stt_ms: null },
  { type: 'assistant.text.delta', v: 1, turn_id: id, text: 'Hello!' },
  { type: 'assistant.audio.started', v: 1, turn_id: id, sample_rate: 24_000 },
]

describe("The tutor's voice", () => {
  it('plays the reply aloud and shows when the tutor speaks', async () => {
    const { socket, user } = await openPractice()

    socket.emitAudio(pcm()) // before any reply: not the tutor's voice
    await user.type(screen.getByLabelText('Message'), 'Hi{Enter}')
    socket.emit(...spokenTurn())
    socket.emitAudio(pcm(), pcm(1_200))
    socket.emit(
      { type: 'assistant.text.done', v: 1, turn_id: 't1', text: 'Hello!', interrupted: false },
      { type: 'assistant.audio.done', v: 1, turn_id: 't1', interrupted: false },
      {
        type: 'turn.metrics',
        v: 1,
        turn_id: 't1',
        first_token_ms: 500,
        reply_ms: 900,
        first_audio_ms: 700,
      },
    )
    socket.emitAudio(pcm()) // after the reply: ignored

    const player = FakePlayer.current
    expect(player?.unlocked).toBe(true)
    expect(player?.played.map((chunk) => [chunk.pcm.byteLength, chunk.sampleRate])).toEqual([
      [4_800, 24_000],
      [2_400, 24_000],
    ])
    expect(screen.getByRole('img', { name: 'Speaking' })).toBeInTheDocument()
    expect(
      screen.getByText('first word 0.5 s · first sound 0.7 s · reply 0.9 s'),
    ).toBeInTheDocument()
    // The reply is written, but the tutor is still talking: it can be stopped.
    expect(screen.getByRole('button', { name: 'Stop' })).toBeInTheDocument()

    player?.finish()
    expect(screen.queryByRole('img', { name: 'Speaking' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Send' })).toBeInTheDocument()
  })

  it('stops talking when interrupted, even with audio still on the way', async () => {
    const { socket, user } = await openPractice()
    socket.emit(...spokenTurn())
    socket.emitAudio(pcm())

    await user.click(screen.getByRole('button', { name: 'Stop' }))
    socket.emitAudio(pcm()) // sent before the server saw the interruption
    socket.emit({ type: 'assistant.audio.started', v: 1, turn_id: 't1', sample_rate: 24_000 })
    socket.emitAudio(pcm())

    const player = FakePlayer.current
    expect(socket.sent.at(-1)).toEqual({ type: 'input.interrupt', v: 1 })
    expect(player?.stops).toBe(1)
    expect(player?.played).toHaveLength(1)

    socket.emit(...spokenTurn('t2'))
    socket.emitAudio(pcm())
    expect(player?.played).toHaveLength(2)
  })

  it('stops talking when the learner starts speaking', async () => {
    const { socket, user } = await openPractice()
    socket.emit(...spokenTurn())
    socket.emitAudio(pcm())
    socket.emit({
      type: 'assistant.text.done',
      v: 1,
      turn_id: 't1',
      text: 'Hello!',
      interrupted: false,
    })

    await user.click(screen.getByRole('button', { name: 'Speak' }))

    expect(socket.sent.at(-1)).toEqual({ type: 'input.interrupt', v: 1 })
    expect(FakePlayer.current?.stops).toBe(1)
  })

  it('can be switched off and on, and remembers the choice', async () => {
    const { socket, user, unmount } = await openPractice()
    socket.emit(...spokenTurn())
    socket.emitAudio(pcm())

    await user.click(screen.getByRole('button', { name: /voice on/i }))

    expect(socket.sent.at(-1)).toEqual({ type: 'session.update', v: 1, speak: false })
    expect(FakePlayer.current?.stops).toBe(1)
    expect(screen.getByRole('button', { name: /voice off/i })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
    unmount()
    expect(FakePlayer.current?.closed).toBe(true)

    const again = await openPractice()
    expect(again.socket.sent[0]).toEqual({ type: 'session.start', v: 1, topic: null, speak: false })
    await again.user.click(screen.getByRole('button', { name: /voice off/i }))
    expect(again.socket.sent.at(-1)).toEqual({ type: 'session.update', v: 1, speak: true })
  })

  it('stays on when the choice cannot be stored', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError')
    })
    const { user } = await openPractice()

    await user.click(screen.getByRole('button', { name: /voice on/i }))

    expect(screen.getByRole('button', { name: /voice off/i })).toBeInTheDocument()
  })

  it('points to the setup when the voice is not installed', async () => {
    const api = fakeApi()
    api.speech.synthesis = { ...api.speech.synthesis, model_ready: false }
    const { user } = renderApp('/practice', api)

    const link = await screen.findByRole('link', { name: /set up the tutor's voice/i })
    FakeSocket.last.open()

    expect(link).toHaveAttribute('href', '/settings')
    expect(FakeSocket.last.sent[0]).toEqual({
      type: 'session.start',
      v: 1,
      topic: null,
      speak: false,
    })

    FakeSocket.last.emit({ type: 'session.ready', v: 1, level: 'B1', provider: 'P', model: 'm' })
    await user.type(screen.getByLabelText('Message'), 'Hi{Enter}')
    expect(FakePlayer.current).toBeUndefined() // no audio without a voice
  })
})

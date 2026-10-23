import { act, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fakeApi } from '@/test/fake-api'
import { FakeMicrophone, FakePlayer, FakeVoiceDetector } from '@/test/fake-audio'
import { FakeSocket, installFakeSocket } from '@/test/fake-socket'
import { renderApp } from '@/test/render-app'

import { reducer, type ServerEvent } from './use-conversation'

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

vi.mock('@/lib/audio/vad', async () => {
  const { FakeVoiceDetector: Detector } = await import('@/test/fake-audio')
  return {
    createVoiceDetector: (...args: Parameters<typeof Detector.create>) => Detector.create(...args),
  }
})

const pcm = () => new Int16Array(2_400).buffer

async function openPractice(api = fakeApi()) {
  const view = renderApp('/practice', api)
  await screen.findByRole('heading', { name: 'Practice' })
  const socket = FakeSocket.last
  socket.open()
  socket.emit({ type: 'session.ready', v: 1, level: 'B1', provider: 'Ollama Cloud', model: 'm' })
  return { ...view, socket }
}

async function startCall() {
  const view = await openPractice()
  await view.user.click(screen.getByRole('button', { name: /^call$/i }))
  const dialog = await screen.findByRole('dialog', { name: 'Call with your tutor' })
  await within(dialog).findByText('Go ahead, I’m listening')
  const detector = FakeVoiceDetector.current
  if (!detector) throw new Error('no voice detector')
  return { ...view, dialog: within(dialog), detector }
}

/** The tutor answers turn `id` out loud. */
function tutorSpeaks(socket: FakeSocket, id = 't1', text = 'Hi there') {
  socket.emit(
    { type: 'transcript.final', v: 1, turn_id: id, text: 'Hello', source: 'voice', stt_ms: 400 },
    { type: 'assistant.text.delta', v: 1, turn_id: id, text },
    { type: 'assistant.audio.started', v: 1, turn_id: id, sample_rate: 24_000 },
  )
  socket.emitAudio(pcm())
}

function finishTurn(socket: FakeSocket, id = 't1', text = 'Hi there') {
  socket.emit(
    { type: 'assistant.text.done', v: 1, turn_id: id, text, interrupted: false },
    { type: 'assistant.audio.done', v: 1, turn_id: id, interrupted: false },
    {
      type: 'turn.metrics',
      v: 1,
      turn_id: id,
      first_token_ms: 300,
      reply_ms: 600,
      first_audio_ms: 500,
    },
  )
  FakePlayer.current?.finish()
}

beforeEach(() => {
  installFakeSocket()
  FakeMicrophone.reset()
  FakePlayer.reset()
  FakeVoiceDetector.reset()
})

describe('Call mode', () => {
  it('opens a call that listens hands-free, with the audio unlocked by the click', async () => {
    const { dialog, detector, socket } = await startCall()

    expect(detector.listening).toBe(true)
    expect(FakePlayer.current?.unlocked).toBe(true)
    expect(dialog.getByText('Level B1')).toBeInTheDocument()
    expect(dialog.getByLabelText('Duration')).toHaveTextContent('0:00')
    expect(screen.getByRole('button', { name: 'End call' })).toHaveFocus()
    expect(socket.sent).toEqual([{ type: 'session.start', v: 1, topic: null, speak: true }])
  })

  it('sends each utterance when the learner stops talking, then speaks the reply', async () => {
    const { dialog, detector, socket } = await startCall()

    detector.startSpeaking()
    expect(dialog.getByText('Listening…')).toBeInTheDocument()
    detector.finishSpeaking(25)

    expect(socket.audio).toHaveLength(25)
    expect(socket.sent.at(-1)).toEqual({ type: 'input.commit', v: 1 })
    expect(dialog.getByText('Thinking…')).toBeInTheDocument()

    tutorSpeaks(socket)
    expect(dialog.getByText('Speaking · talk to interrupt')).toBeInTheDocument()
    expect(detector.strict).toBe(true) // the tutor's own voice must not count as the learner's
    const captions = within(dialog.getByLabelText('Live captions'))
    expect(captions.getByText('Hello')).toBeInTheDocument()
    expect(captions.getByText('Hi there')).toBeInTheDocument()

    finishTurn(socket)
    expect(dialog.getByText('Go ahead, I’m listening')).toBeInTheDocument()
    expect(detector.strict).toBe(false)
  })

  it('stays thinking while the reply is written, until it is complete', async () => {
    const { dialog, detector, socket } = await startCall()
    detector.say()
    socket.emit({
      type: 'transcript.final',
      v: 1,
      turn_id: 't1',
      text: 'Hello',
      source: 'voice',
      stt_ms: 400,
    })

    expect(dialog.getByText('Thinking…')).toBeInTheDocument()
  })

  it('lets the learner interrupt the tutor by talking', async () => {
    const { dialog, detector, socket } = await startCall()
    detector.say()
    tutorSpeaks(socket)

    detector.startSpeaking()

    expect(socket.sent.at(-1)).toEqual({ type: 'input.interrupt', v: 1 })
    expect(FakePlayer.current?.stops).toBeGreaterThan(0)
    expect(dialog.getByText('Listening…')).toBeInTheDocument()
  })

  it('ignores a cough', async () => {
    const { dialog, detector, socket } = await startCall()

    detector.cough()

    expect(socket.audio).toEqual([])
    expect(dialog.getByText('Go ahead, I’m listening')).toBeInTheDocument()
  })

  it('mutes and unmutes the microphone', async () => {
    const { dialog, detector, user } = await startCall()

    await user.click(dialog.getByRole('button', { name: 'Mute' }))
    expect(detector.listening).toBe(false)
    expect(dialog.getByText('Muted')).toBeInTheDocument()

    await user.click(dialog.getByRole('button', { name: 'Unmute' }))
    expect(detector.listening).toBe(true)
  })

  it('hides the captions and counts corrections for after the call', async () => {
    const { dialog, detector, socket, user } = await startCall()
    detector.say()
    tutorSpeaks(socket)
    socket.emit({
      type: 'correction',
      v: 1,
      turn_id: 't1',
      corrected: 'Hello!',
      latency_ms: 900,
      items: [
        { original: 'a', suggestion: 'b', kind: 'grammar', explanation: 'x' },
        { original: 'c', suggestion: 'd', kind: 'vocabulary', explanation: 'y' },
      ],
    })

    expect(dialog.getByText('2 corrections to review after the call')).toBeInTheDocument()
    await user.click(dialog.getByRole('button', { name: 'Captions' }))
    expect(dialog.queryByLabelText('Live captions')).not.toBeInTheDocument()
  })

  it('ends the call, silencing the tutor, and goes back to the chat', async () => {
    const { detector, socket, user } = await startCall()
    detector.say()
    tutorSpeaks(socket)

    await user.click(screen.getByRole('button', { name: 'End call' }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(detector.destroyed).toBe(true)
    expect(socket.sent.at(-1)).toEqual({ type: 'input.interrupt', v: 1 })
    expect(screen.getByRole('list', { name: 'Conversation' })).toHaveTextContent('Hello')
  })

  it('ends with Escape too, without interrupting a finished reply', async () => {
    const { detector, socket, user } = await startCall()
    detector.say()
    tutorSpeaks(socket)
    finishTurn(socket)
    const sent = socket.sent.length

    await user.keyboard('a')
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    await user.keyboard('{Escape}')

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(socket.sent).toHaveLength(sent)
  })

  it('turns the voice on for the call when the learner switched it off', async () => {
    window.localStorage.setItem('voice-tutor:voice-replies', 'off')
    const { socket, user } = await openPractice()

    await user.click(screen.getByRole('button', { name: /^call$/i }))
    await screen.findByText('Go ahead, I’m listening')
    expect(socket.sent.at(-1)).toEqual({ type: 'session.update', v: 1, speak: true })

    await user.click(screen.getByRole('button', { name: 'End call' }))
    expect(socket.sent.at(-1)).toEqual({ type: 'session.update', v: 1, speak: false })
  })

  it('says "correction" for a single one', async () => {
    const { dialog, detector, socket } = await startCall()
    detector.say()
    tutorSpeaks(socket)
    socket.emit({
      type: 'correction',
      v: 1,
      turn_id: 't1',
      corrected: 'Hello!',
      latency_ms: 900,
      items: [{ original: 'a', suggestion: 'b', kind: 'grammar', explanation: 'x' }],
    })

    expect(dialog.getByText('1 correction to review after the call')).toBeInTheDocument()
  })

  it('takes over the microphone from push-to-talk', async () => {
    const { user } = await openPractice()
    await user.click(screen.getByRole('button', { name: 'Speak' }))
    expect(FakeMicrophone.current?.recording).toBe(true)

    await user.click(screen.getByRole('button', { name: /^call$/i }))

    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(FakeMicrophone.current?.recording).toBe(false)
  })

  it('starts from the empty conversation too', async () => {
    const { user } = await openPractice()

    await user.click(screen.getByRole('button', { name: /start a call/i }))

    expect(await screen.findByRole('dialog')).toBeInTheDocument()
  })

  it('explains microphone problems', async () => {
    FakeVoiceDetector.failWith = new DOMException('denied', 'NotAllowedError')
    const { user } = await openPractice()

    await user.click(screen.getByRole('button', { name: /^call$/i }))

    expect(await screen.findByText('The microphone did not start')).toBeInTheDocument()
    expect(screen.getByText(/Microphone access was denied/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Mute' })).toBeDisabled()
  })

  it('shows speech recognition problems during the call', async () => {
    const { dialog, detector, socket } = await startCall()
    detector.say()

    socket.emit({
      type: 'error',
      v: 1,
      code: 'no_speech',
      message: 'I did not catch that.',
      retryable: true,
    })

    expect(dialog.getByText('I did not catch that.')).toBeInTheDocument()
    expect(dialog.getByText('Go ahead, I’m listening')).toBeInTheDocument()
  })

  it('stops the microphone when the call ends while it is still starting', async () => {
    let loaded!: () => void
    FakeVoiceDetector.loading = new Promise<void>((resolve) => {
      loaded = resolve
    })
    const { user } = await openPractice()
    await user.click(screen.getByRole('button', { name: /^call$/i }))
    expect(await screen.findByText('Connecting…')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'End call' }))
    await act(async () => {
      loaded()
      await Promise.resolve()
    })

    expect(FakeVoiceDetector.current?.destroyed).toBe(true)
    expect(FakeVoiceDetector.current?.listening).toBe(false)
  })

  it('forgets a microphone failure that comes after the call ended', async () => {
    let loaded!: () => void
    FakeVoiceDetector.loading = new Promise<void>((resolve) => {
      loaded = resolve
    })
    FakeVoiceDetector.failWith = new DOMException('denied', 'NotAllowedError')
    const { user } = await openPractice()
    await user.click(screen.getByRole('button', { name: /^call$/i }))
    await screen.findByText('Connecting…')

    await user.click(screen.getByRole('button', { name: 'End call' }))
    await act(async () => {
      loaded()
      await Promise.resolve()
    })

    expect(screen.queryByText(/Microphone access was denied/)).not.toBeInTheDocument()
  })

  it('needs speech recognition and the voice set up', async () => {
    const api = fakeApi()
    api.speech.recognition = { ...api.speech.recognition, model_ready: false }
    await openPractice(api)

    expect(await screen.findByRole('button', { name: /^call$/i })).toBeDisabled()
    expect(screen.queryByRole('button', { name: /start a call/i })).not.toBeInTheDocument()
  })

  it('makes the orb follow the voice of whoever talks', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      const { detector, socket } = await startCall()
      detector.say()
      tutorSpeaks(socket)
      const player = FakePlayer.current
      if (!player) throw new Error('no player')
      player.loudness = 0.2

      await act(() => vi.advanceTimersByTimeAsync(500))

      const orb = document.querySelector('.orb')
      expect(orb).toHaveAttribute('data-phase', 'speaking')
      expect(Number((orb as HTMLElement).style.getPropertyValue('--orb-level'))).toBeGreaterThan(
        0.5,
      )
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('transcription state', () => {
  const start = { status: 'open' as const, turns: [], transcribing: true }
  const error = (code: Extract<ServerEvent, { type: 'error' }>['code']) =>
    ({ type: 'error', v: 1, code, message: 'm', retryable: true }) as const

  it('ends with a speech error, not with others', () => {
    expect(reducer(start, error('no_speech')).transcribing).toBe(false)
    expect(reducer(start, error('tts_failed')).transcribing).toBe(true)
  })
})

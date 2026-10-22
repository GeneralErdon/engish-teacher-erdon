import { act, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { FakeMicrophone } from '@/test/fake-audio'
import { FakeSocket, installFakeSocket } from '@/test/fake-socket'
import { renderApp } from '@/test/render-app'

vi.mock('@/lib/audio/web-audio-source', async () => {
  const { FakeMicrophone: Microphone } = await import('@/test/fake-audio')
  return { createWebAudioSource: () => new Microphone() }
})

async function openPractice() {
  const view = renderApp('/practice')
  await screen.findByRole('heading', { name: 'Practice' })
  const socket = FakeSocket.last
  socket.open()
  socket.emit({ type: 'session.ready', v: 1, level: 'B1', provider: 'Ollama Cloud', model: 'm' })
  return { ...view, socket }
}

beforeEach(() => {
  installFakeSocket()
  FakeMicrophone.reset()
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

import { afterEach, describe, expect, it, vi } from 'vitest'

import { createWebAudioSource } from './web-audio-source'

class FakeNode {
  port = { onmessage: null as ((event: MessageEvent<ArrayBuffer>) => void) | null }
  readonly name: string
  constructor(_context: FakeContext, name: string) {
    this.name = name
    FakeContext.last.node = this
  }
}

class FakeContext {
  static last: FakeContext
  static failModule = false
  node: FakeNode | undefined
  connected = false
  closed = false
  audioWorklet = {
    addModule: vi.fn((url: string) =>
      FakeContext.failModule ? Promise.reject(new Error(`cannot load ${url}`)) : Promise.resolve(),
    ),
  }
  constructor() {
    FakeContext.last = this
  }
  createMediaStreamSource() {
    return {
      connect: (node: FakeNode) => {
        this.connected = node === this.node
      },
    }
  }
  close() {
    this.closed = true
    return Promise.resolve()
  }
}

function install(getUserMedia: () => Promise<unknown>) {
  vi.stubGlobal('AudioContext', FakeContext)
  vi.stubGlobal('AudioWorkletNode', FakeNode)
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } })
}

const track = { stop: vi.fn() }
const stream = { getTracks: () => [track] }

afterEach(() => {
  FakeContext.failModule = false
  track.stop.mockClear()
})

describe('createWebAudioSource', () => {
  it('connects the microphone to the PCM worklet and forwards its frames', async () => {
    const getUserMedia = vi.fn(() => Promise.resolve(stream))
    install(getUserMedia)
    const frames: ArrayBuffer[] = []
    const source = createWebAudioSource('/w.js')

    await source.start((pcm) => frames.push(pcm))
    const context = FakeContext.last
    context.node?.port.onmessage?.(new MessageEvent('message', { data: new ArrayBuffer(640) }))

    expect(getUserMedia).toHaveBeenCalledWith({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    })
    expect(context.audioWorklet.addModule).toHaveBeenCalledWith('/w.js')
    expect(context.node?.name).toBe('pcm-recorder')
    expect(context.connected).toBe(true)
    expect(frames).toHaveLength(1)

    await source.stop()
    expect(track.stop).toHaveBeenCalled()
    expect(context.closed).toBe(true)
    await source.stop() // already stopped: nothing to do
  })

  it('releases the microphone when the worklet cannot load', async () => {
    install(() => Promise.resolve(stream))
    FakeContext.failModule = true
    const source = createWebAudioSource()

    await expect(source.start(() => undefined)).rejects.toThrow(
      'cannot load /pcm-recorder.worklet.js',
    )
    expect(track.stop).toHaveBeenCalled()
    expect(FakeContext.last.closed).toBe(true)
  })

  it('needs a secure context', async () => {
    vi.stubGlobal('navigator', {})

    await expect(createWebAudioSource().start(() => undefined)).rejects.toThrow(
      'the microphone needs HTTPS or localhost',
    )
  })
})

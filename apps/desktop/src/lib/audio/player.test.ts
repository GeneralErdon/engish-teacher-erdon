import { describe, expect, it, vi } from 'vitest'

import { createVoicePlayer } from './player'

class FakeBuffer {
  readonly length: number
  readonly sampleRate: number
  readonly data: Float32Array
  readonly duration: number
  constructor(length: number, sampleRate: number) {
    this.length = length
    this.sampleRate = sampleRate
    this.data = new Float32Array(length)
    this.duration = length / sampleRate
  }
  getChannelData() {
    return this.data
  }
}

class FakeSource {
  buffer: FakeBuffer | null = null
  startedAt: number | undefined
  stopped = false
  destination: unknown
  onended: (() => void) | null = null
  connect(destination: unknown) {
    this.destination = destination
  }
  start(when: number) {
    this.startedAt = when
  }
  stop() {
    this.stopped = true
  }
}

class FakeAnalyser {
  fftSize = 2048
  destination: unknown
  /** What the analyser "hears" right now. */
  signal = 0
  connect(destination: unknown) {
    this.destination = destination
  }
  getFloatTimeDomainData(samples: Float32Array) {
    samples.fill(this.signal)
  }
}

class FakeContext {
  static last: FakeContext
  state: AudioContextState = 'suspended'
  currentTime = 10
  destination = { speakers: true }
  analyser = new FakeAnalyser()
  sources: FakeSource[] = []
  closed = false
  resume = vi.fn(() => {
    this.state = 'running'
    return Promise.resolve()
  })
  constructor() {
    FakeContext.last = this
  }
  createBuffer(_channels: number, length: number, sampleRate: number) {
    return new FakeBuffer(length, sampleRate)
  }
  createAnalyser() {
    return this.analyser
  }
  createBufferSource() {
    const source = new FakeSource()
    this.sources.push(source)
    return source
  }
  close() {
    this.closed = true
    return Promise.resolve()
  }
}

/** `samples` PCM16 samples at `value`. */
const pcm = (samples: number, value = 0x4000) => new Int16Array(samples).fill(value).buffer

function setup() {
  vi.stubGlobal('AudioContext', FakeContext)
  const changes: boolean[] = []
  const player = createVoicePlayer((playing) => changes.push(playing))
  return { player, changes }
}

describe('createVoicePlayer', () => {
  it('plays chunks back to back, converted to floats at their own rate', () => {
    const { player, changes } = setup()

    player.play(pcm(2_400), 24_000) // 0.1 s
    player.play(pcm(4_800, -0x8000), 24_000) // 0.2 s
    const context = FakeContext.last
    const [first, second] = context.sources

    expect(context.resume).toHaveBeenCalled()
    expect(first?.buffer?.sampleRate).toBe(24_000)
    expect(first?.buffer?.data[0]).toBe(0.5)
    expect(second?.buffer?.data[0]).toBe(-1)
    expect(first?.destination).toBe(context.analyser)
    expect(context.analyser.destination).toBe(context.destination)
    expect(first?.startedAt).toBeCloseTo(10.05)
    expect(second?.startedAt).toBeCloseTo(10.15)
    expect(changes).toEqual([true])

    first?.onended?.()
    expect(changes).toEqual([true])
    second?.onended?.()
    expect(changes).toEqual([true, false])
  })

  it('measures the level of what is playing', () => {
    const { player } = setup()
    expect(player.level()).toBe(0) // nothing created yet

    player.play(pcm(2_400), 24_000)
    const context = FakeContext.last
    context.analyser.signal = 0.25

    expect(context.analyser.fftSize).toBe(512)
    expect(player.level()).toBeCloseTo(0.25)
    context.sources[0]?.onended?.()
    expect(player.level()).toBe(0) // silent again
  })

  it('starts again from now after a pause', () => {
    const { player } = setup()
    player.play(pcm(2_400), 24_000)
    const context = FakeContext.last
    context.sources[0]?.onended?.()

    context.currentTime = 30
    player.play(pcm(2_400), 24_000)

    expect(context.sources[1]?.startedAt).toBeCloseTo(30.05)
  })

  it('stops at once and forgets the queue', () => {
    const { player, changes } = setup()
    player.play(pcm(2_400), 24_000)
    player.play(pcm(2_400), 24_000)
    const context = FakeContext.last

    player.stop()
    player.stop() // already silent: no second change

    expect(context.sources.every((source) => source.stopped)).toBe(true)
    expect(changes).toEqual([true, false])
    player.play(pcm(2_400), 24_000)
    expect(context.sources[2]?.startedAt).toBeCloseTo(10.05)
  })

  it('ignores empty chunks and a trailing half sample', () => {
    const { player } = setup()

    player.play(new ArrayBuffer(1), 24_000)
    player.unlock()
    player.play(new ArrayBuffer(5), 24_000)

    expect(FakeContext.last.sources).toHaveLength(1)
    expect(FakeContext.last.sources[0]?.buffer?.length).toBe(2)
  })

  it('creates the audio context on a gesture and closes it at the end', async () => {
    const { player } = setup()

    player.unlock()
    const context = FakeContext.last
    expect(context.resume).toHaveBeenCalledOnce()
    player.unlock() // already running
    expect(context.resume).toHaveBeenCalledOnce()

    await player.close()
    expect(context.closed).toBe(true)
    await player.close() // nothing left to close
  })
})

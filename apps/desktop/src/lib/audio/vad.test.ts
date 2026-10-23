import { afterEach, describe, expect, it, vi } from 'vitest'

import type { RealTimeVADOptions } from '@ricky0123/vad-web'

import { createVoiceDetector, toPcm16Frames, VAD_ASSETS, type VoiceDetectorEvents } from './vad'

const micVad = {
  start: vi.fn(() => Promise.resolve()),
  pause: vi.fn(() => Promise.resolve()),
  destroy: vi.fn(() => Promise.resolve()),
  setOptions: vi.fn(),
}
let options: Partial<RealTimeVADOptions> = {}

vi.mock('@ricky0123/vad-web', () => ({
  MicVAD: {
    new: vi.fn((given: Partial<RealTimeVADOptions>) => {
      options = given
      return Promise.resolve(micVad)
    }),
  },
}))

function events(): VoiceDetectorEvents & Record<string, ReturnType<typeof vi.fn>> {
  return {
    onSpeechStart: vi.fn(),
    onSpeechConfirmed: vi.fn(),
    onSpeechEnd: vi.fn(),
    onMisfire: vi.fn(),
    onLevel: vi.fn(),
  }
}

const getUserMedia = vi.fn<(constraints: MediaStreamConstraints) => Promise<MediaStream>>(() =>
  Promise.resolve({} as MediaStream),
)

afterEach(() => {
  vi.clearAllMocks()
})

describe('toPcm16Frames', () => {
  it('cuts float samples into 20 ms PCM16 frames, clipping out-of-range values', () => {
    const audio = new Float32Array(700).fill(0.5)
    audio[0] = 2
    audio[1] = -2

    const frames = toPcm16Frames(audio)

    expect(frames.map((frame) => frame.byteLength)).toEqual([640, 640, 120])
    const first = new Int16Array(frames[0] ?? new ArrayBuffer(0))
    expect([first[0], first[1], first[2]]).toEqual([0x7fff, -0x7fff, 16384])
  })
})

describe('createVoiceDetector', () => {
  it('runs Silero v5 from the app, listens with echo cancellation and maps its events', async () => {
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } })
    const handlers = events()

    const detector = await createVoiceDetector(handlers)

    expect(options).toMatchObject({
      model: 'v5',
      baseAssetPath: VAD_ASSETS,
      onnxWASMBasePath: VAD_ASSETS,
      positiveSpeechThreshold: 0.5,
      startOnLoad: false,
    })
    await options.getStream?.()
    expect(getUserMedia.mock.calls[0]?.[0].audio).toMatchObject({
      echoCancellation: true,
      noiseSuppression: true,
    })

    await options.onSpeechStart?.()
    await options.onSpeechRealStart?.()
    await options.onVADMisfire?.()
    await options.onSpeechEnd?.(new Float32Array(320))
    await options.onFrameProcessed?.(
      { isSpeech: 0.9, notSpeech: 0.1 },
      new Float32Array(4).fill(0.5),
    )

    expect(handlers.onSpeechStart).toHaveBeenCalledOnce()
    expect(handlers.onSpeechConfirmed).toHaveBeenCalledOnce()
    expect(handlers.onMisfire).toHaveBeenCalledOnce()
    expect(handlers.onSpeechEnd).toHaveBeenCalledWith([expect.any(ArrayBuffer)])
    expect(handlers.onLevel).toHaveBeenCalledWith(0.5)

    await detector.start()
    detector.setStrict(true)
    detector.setStrict(false)
    await detector.pause()
    await detector.destroy()
    expect(micVad.start).toHaveBeenCalledOnce()
    expect(micVad.setOptions.mock.calls).toEqual([
      [{ positiveSpeechThreshold: 0.8, negativeSpeechThreshold: 0.65 }],
      [{ positiveSpeechThreshold: 0.5, negativeSpeechThreshold: 0.35 }],
    ])
    expect(micVad.pause).toHaveBeenCalledOnce()
    expect(micVad.destroy).toHaveBeenCalledOnce()
  })

  it('needs a secure page for the microphone', async () => {
    vi.stubGlobal('navigator', {})

    await expect(createVoiceDetector(events())).rejects.toThrow('HTTPS or localhost')
  })
})

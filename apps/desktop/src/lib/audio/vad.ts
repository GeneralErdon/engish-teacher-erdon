import { rms } from './source'

/** Where vite.config.ts serves the worklet, the Silero model and ONNX Runtime. */
export const VAD_ASSETS = '/vad/'

const FRAME_SAMPLES = 320 // 20 ms at 16 kHz, as the push-to-talk recorder sends

export interface VoiceDetectorEvents {
  /** Speech may be starting (it can still turn out to be a cough). */
  onSpeechStart: () => void
  /** Speech went on long enough to be real: safe to interrupt the tutor. */
  onSpeechConfirmed: () => void
  /** A finished utterance: PCM16 mono at 16 kHz, in 20 ms frames, ready for the session. */
  onSpeechEnd: (frames: ArrayBuffer[]) => void
  /** It was too short to be speech. */
  onMisfire: () => void
  /** Microphone loudness, 0..1, about 30 times a second. */
  onLevel: (level: number) => void
}

/** Hands-free listening: the microphone, Silero VAD (on ONNX Runtime, in the browser) and turn ends. */
export interface VoiceDetector {
  start(): Promise<void>
  pause(): Promise<void>
  /** Harder to trigger while the tutor speaks, so its voice from the speakers is not the learner's. */
  setStrict(strict: boolean): void
  destroy(): Promise<void>
}

const NORMAL = { positiveSpeechThreshold: 0.5, negativeSpeechThreshold: 0.35 }
const STRICT = { positiveSpeechThreshold: 0.8, negativeSpeechThreshold: 0.65 }

/** Float samples (-1..1) to PCM16 little-endian, in 20 ms frames. */
export function toPcm16Frames(audio: Float32Array): ArrayBuffer[] {
  const frames: ArrayBuffer[] = []
  for (let start = 0; start < audio.length; start += FRAME_SAMPLES) {
    const chunk = audio.subarray(start, start + FRAME_SAMPLES)
    const pcm = Int16Array.from(chunk, (sample) =>
      Math.round(Math.max(-1, Math.min(1, sample)) * 0x7fff),
    )
    frames.push(pcm.buffer)
  }
  return frames
}

export async function createVoiceDetector(events: VoiceDetectorEvents): Promise<VoiceDetector> {
  // Undefined outside secure contexts: the microphone needs HTTPS or localhost.
  if (!(navigator.mediaDevices as MediaDevices | undefined)) {
    throw new Error('the microphone needs HTTPS or localhost')
  }
  // Loaded on first call only: ONNX Runtime and the model are megabytes the chat never needs.
  const { MicVAD } = await import('@ricky0123/vad-web')
  const vad = await MicVAD.new({
    model: 'v5',
    baseAssetPath: VAD_ASSETS,
    onnxWASMBasePath: VAD_ASSETS,
    ...NORMAL,
    // Silence that ends a turn: long enough for a learner to look for a word.
    redemptionMs: 900,
    minSpeechMs: 400,
    preSpeechPadMs: 300,
    startOnLoad: false,
    // No sample rate here: Firefox and WebKit refuse to connect a microphone at another rate than
    // the AudioContext's. The worklet resamples to 16 kHz itself.
    getStream: () =>
      navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      }),
    onSpeechStart: events.onSpeechStart,
    onSpeechRealStart: events.onSpeechConfirmed,
    onSpeechEnd: (audio) => {
      events.onSpeechEnd(toPcm16Frames(audio))
    },
    onVADMisfire: events.onMisfire,
    onFrameProcessed: (_probabilities, frame) => {
      events.onLevel(rms(frame))
    },
  })
  return {
    start: () => vad.start(),
    pause: () => vad.pause(),
    setStrict: (strict) => {
      vad.setOptions(strict ? STRICT : NORMAL)
    },
    destroy: () => vad.destroy(),
  }
}

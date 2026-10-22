import { rms } from './source'

/**
 * Plays the tutor's voice: chunks of PCM16 mono, scheduled back to back as they arrive, so
 * sentences synthesised one at a time sound like one reply.
 */
export interface VoicePlayer {
  /** Queue `pcm` after what is already queued. */
  play(pcm: ArrayBuffer, sampleRate: number): void
  /** Silence at once and drop the queue (the learner interrupted). */
  stop(): void
  /** Browsers start audio only after a user gesture: call this from one (a click, a key). */
  unlock(): void
  /** Loudness of what is playing right now, 0..1 (for call mode's orb). */
  level(): number
  close(): Promise<void>
}

/** Delay before a chunk that starts from silence, so it never starts in the past and clicks. */
const LEAD_S = 0.05

/** Web Audio playback; `onPlayingChange` reports when the voice starts and stops. */
export function createVoicePlayer(onPlayingChange: (playing: boolean) => void): VoicePlayer {
  let output: { context: AudioContext; analyser: AnalyserNode } | undefined
  let samples: Float32Array<ArrayBuffer> | undefined
  let queuedUntil = 0
  const sources = new Set<AudioBufferSourceNode>()

  const audio = () => {
    if (!output) {
      const context = new AudioContext()
      // Everything plays through the analyser, which measures the level on its way out.
      const analyser = context.createAnalyser()
      analyser.fftSize = 512
      analyser.connect(context.destination)
      output = { context, analyser }
    }
    if (output.context.state === 'suspended') void output.context.resume()
    return output
  }

  const stop = () => {
    const wasPlaying = sources.size > 0
    for (const source of sources) {
      source.onended = null
      source.stop()
    }
    sources.clear()
    queuedUntil = 0
    if (wasPlaying) onPlayingChange(false)
  }

  return {
    play(pcm, sampleRate) {
      const pcm16 = new Int16Array(pcm, 0, pcm.byteLength >> 1)
      if (pcm16.length === 0) return
      const { context, analyser } = audio()
      // The context plays at the device rate and resamples the buffer itself.
      const buffer = context.createBuffer(1, pcm16.length, sampleRate)
      buffer.getChannelData(0).set(Float32Array.from(pcm16, (sample) => sample / 0x8000))
      const source = context.createBufferSource()
      source.buffer = buffer
      source.connect(analyser)
      const startAt = Math.max(queuedUntil, context.currentTime + LEAD_S)
      source.start(startAt)
      queuedUntil = startAt + buffer.duration
      source.onended = () => {
        sources.delete(source)
        if (sources.size === 0) onPlayingChange(false)
      }
      if (sources.size === 0) onPlayingChange(true)
      sources.add(source)
    },
    stop,
    unlock() {
      audio()
    },
    level() {
      if (!output || sources.size === 0) return 0
      samples ??= new Float32Array(output.analyser.fftSize)
      output.analyser.getFloatTimeDomainData(samples)
      return rms(samples)
    },
    async close() {
      stop()
      const open = output
      output = undefined
      await open?.context.close()
    },
  }
}

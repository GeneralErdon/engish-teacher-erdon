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
  close(): Promise<void>
}

/** Delay before a chunk that starts from silence, so it never starts in the past and clicks. */
const LEAD_S = 0.05

/** Web Audio playback; `onPlayingChange` reports when the voice starts and stops. */
export function createVoicePlayer(onPlayingChange: (playing: boolean) => void): VoicePlayer {
  let context: AudioContext | undefined
  let queuedUntil = 0
  const sources = new Set<AudioBufferSourceNode>()

  const audio = () => {
    context ??= new AudioContext()
    if (context.state === 'suspended') void context.resume()
    return context
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
      const samples = new Int16Array(pcm, 0, pcm.byteLength >> 1)
      if (samples.length === 0) return
      const output = audio()
      // The context plays at the device rate and resamples the buffer itself.
      const buffer = output.createBuffer(1, samples.length, sampleRate)
      buffer.getChannelData(0).set(Float32Array.from(samples, (sample) => sample / 0x8000))
      const source = output.createBufferSource()
      source.buffer = buffer
      source.connect(output.destination)
      const startAt = Math.max(queuedUntil, output.currentTime + LEAD_S)
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
    async close() {
      stop()
      const open = context
      context = undefined
      await open?.close()
    },
  }
}

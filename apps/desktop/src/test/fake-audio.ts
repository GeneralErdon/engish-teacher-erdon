import { act } from '@testing-library/react'

import type { VoicePlayer } from '@/lib/audio/player'
import type { AudioSource } from '@/lib/audio/source'

/** A microphone for tests: `speak()` pushes frames to whoever is recording. */
export class FakeMicrophone implements AudioSource {
  static current: FakeMicrophone | undefined
  static failWith: Error | undefined

  recording = false
  private onFrame: ((pcm: ArrayBuffer) => void) | undefined

  constructor() {
    FakeMicrophone.current = this
  }

  start(onFrame: (pcm: ArrayBuffer) => void): Promise<void> {
    if (FakeMicrophone.failWith) return Promise.reject(FakeMicrophone.failWith)
    this.onFrame = onFrame
    this.recording = true
    return Promise.resolve()
  }

  stop(): Promise<void> {
    this.recording = false
    return Promise.resolve()
  }

  /** `frames` frames of 20 ms at a constant level (0..1). */
  speak(frames: number, loudness = 0.5) {
    act(() => {
      for (let i = 0; i < frames; i++) {
        this.onFrame?.(new Int16Array(320).fill(Math.round(loudness * 0x7fff)).buffer)
      }
    })
  }

  static reset() {
    FakeMicrophone.current = undefined
    FakeMicrophone.failWith = undefined
  }
}

/** Speakers for tests: records what would play; `finish()` ends the playback. */
export class FakePlayer implements VoicePlayer {
  static current: FakePlayer | undefined

  readonly played: { pcm: ArrayBuffer; sampleRate: number }[] = []
  unlocked = false
  stops = 0
  closed = false
  private readonly onPlayingChange: (playing: boolean) => void

  constructor(onPlayingChange: (playing: boolean) => void) {
    this.onPlayingChange = onPlayingChange
    FakePlayer.current = this
  }

  play(pcm: ArrayBuffer, sampleRate: number) {
    this.played.push({ pcm, sampleRate })
    this.onPlayingChange(true)
  }

  stop() {
    this.stops++
    this.onPlayingChange(false)
  }

  unlock() {
    this.unlocked = true
  }

  close() {
    this.closed = true
    return Promise.resolve()
  }

  /** Everything queued has been played. */
  finish() {
    act(() => {
      this.onPlayingChange(false)
    })
  }

  static reset() {
    FakePlayer.current = undefined
  }
}

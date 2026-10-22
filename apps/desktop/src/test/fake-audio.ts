import { act } from '@testing-library/react'

import type { VoicePlayer } from '@/lib/audio/player'
import type { AudioSource } from '@/lib/audio/source'
import type { VoiceDetector, VoiceDetectorEvents } from '@/lib/audio/vad'

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
  /** What `level()` reports. */
  loudness = 0
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

  level() {
    return this.loudness
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

/** Call mode's voice detector for tests: `say()` and friends play the detector's events. */
export class FakeVoiceDetector implements VoiceDetector {
  static current: FakeVoiceDetector | undefined
  static failWith: Error | undefined
  /** When set, `create()` waits for it (the model is still loading). */
  static loading: Promise<void> | undefined

  listening = false
  strict = false
  destroyed = false
  private readonly events: VoiceDetectorEvents

  constructor(events: VoiceDetectorEvents) {
    this.events = events
    FakeVoiceDetector.current = this
  }

  static async create(events: VoiceDetectorEvents): Promise<VoiceDetector> {
    await FakeVoiceDetector.loading
    if (FakeVoiceDetector.failWith) throw FakeVoiceDetector.failWith
    return new FakeVoiceDetector(events)
  }

  start() {
    this.listening = true
    return Promise.resolve()
  }

  pause() {
    this.listening = false
    return Promise.resolve()
  }

  setStrict(strict: boolean) {
    this.strict = strict
  }

  destroy() {
    this.listening = false
    this.destroyed = true
    return Promise.resolve()
  }

  /** The learner says something: speech starts, is confirmed, and ends `frames` frames later. */
  say(frames = 25) {
    this.startSpeaking()
    this.finishSpeaking(frames)
  }

  startSpeaking() {
    act(() => {
      this.events.onSpeechStart()
      this.events.onLevel(0.2)
      this.events.onSpeechConfirmed()
    })
  }

  finishSpeaking(frames = 25) {
    act(() => {
      this.events.onSpeechEnd(Array.from({ length: frames }, () => new ArrayBuffer(640)))
    })
  }

  /** A cough: speech starts, then turns out too short. */
  cough() {
    act(() => {
      this.events.onSpeechStart()
      this.events.onMisfire()
    })
  }

  static reset() {
    FakeVoiceDetector.current = undefined
    FakeVoiceDetector.failWith = undefined
    FakeVoiceDetector.loading = undefined
  }
}

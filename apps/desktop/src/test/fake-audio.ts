import { act } from '@testing-library/react'

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

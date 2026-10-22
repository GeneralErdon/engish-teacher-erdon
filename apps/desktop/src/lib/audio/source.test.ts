import { describe, expect, it } from 'vitest'

import { level, microphoneError } from './source'

describe('level', () => {
  it('is the RMS of the frame, 0..1', () => {
    expect(level(new ArrayBuffer(0))).toBe(0)
    expect(level(new Int16Array(320).buffer)).toBe(0)
    expect(level(new Int16Array(320).fill(-0x8000).buffer)).toBe(1)
  })
})

describe('microphoneError', () => {
  it('explains the usual failures', () => {
    expect(microphoneError(new DOMException('', 'NotAllowedError'))).toMatch(/was denied/)
    expect(microphoneError(new DOMException('', 'NotFoundError'))).toBe('No microphone was found.')
    expect(microphoneError(new Error('busy'))).toBe('Could not start the microphone: busy')
    expect(microphoneError('odd')).toBe('Could not start the microphone: odd')
  })
})

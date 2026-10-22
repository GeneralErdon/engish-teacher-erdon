import { describe, expect, it } from 'vitest'

import { wordDiff } from './diff'

describe('wordDiff', () => {
  it('marks replaced words', () => {
    expect(wordDiff('Yesterday I have went to the beach', 'Yesterday I went to the beach')).toEqual(
      [
        { kind: 'same', text: 'Yesterday I' },
        { kind: 'removed', text: 'have' },
        { kind: 'same', text: 'went to the beach' },
      ],
    )
  })

  it('marks additions and removals at both ends', () => {
    expect(wordDiff('went to beach yesterday please', 'I went to the beach yesterday')).toEqual([
      { kind: 'added', text: 'I' },
      { kind: 'same', text: 'went to' },
      { kind: 'added', text: 'the' },
      { kind: 'same', text: 'beach yesterday' },
      { kind: 'removed', text: 'please' },
    ])
  })

  it('ignores capitalisation and punctuation, showing the corrected form', () => {
    expect(wordDiff('i am fine', 'I am fine.')).toEqual([{ kind: 'same', text: 'I am fine.' }])
  })

  it('handles empty text', () => {
    expect(wordDiff('', 'Hello')).toEqual([{ kind: 'added', text: 'Hello' }])
    expect(wordDiff('Hello', '')).toEqual([{ kind: 'removed', text: 'Hello' }])
  })
})

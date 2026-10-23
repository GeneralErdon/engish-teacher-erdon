/* eslint-disable @typescript-eslint/no-non-null-assertion -- every index below is bounded by
   its loop; `noUncheckedIndexedAccess` cannot see that. */
export interface Segment {
  kind: 'same' | 'removed' | 'added'
  text: string
}

/** Words only, lower case: capitalisation and punctuation are not mistakes here. */
const key = (word: string) => word.toLowerCase().replace(/[^\p{L}\p{N}']+/gu, '')

/**
 * Word-level diff of the learner's text and its correction (longest common subsequence),
 * merged into runs: what to strike through in red, what to add in green.
 */
export function wordDiff(original: string, corrected: string): Segment[] {
  const a = original.split(/\s+/).filter(Boolean)
  const b = corrected.split(/\s+/).filter(Boolean)
  // lcs[i][j]: length of the LCS of a[i:] and b[j:].
  const lcs = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0))
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      lcs[i]![j] =
        key(a[i]!) === key(b[j]!)
          ? lcs[i + 1]![j + 1]! + 1
          : Math.max(lcs[i + 1]![j]!, lcs[i]![j + 1]!)
    }
  }

  const segments: Segment[] = []
  const push = (kind: Segment['kind'], word: string) => {
    const last = segments.at(-1)
    if (last?.kind === kind) last.text += ` ${word}`
    else segments.push({ kind, text: word })
  }
  let i = 0
  let j = 0
  while (i < a.length && j < b.length) {
    if (key(a[i]!) === key(b[j]!)) {
      push('same', b[j]!)
      i++
      j++
    } else if (lcs[i + 1]![j]! >= lcs[i]![j + 1]!) {
      push('removed', a[i++]!)
    } else {
      push('added', b[j++]!)
    }
  }
  while (i < a.length) push('removed', a[i++]!)
  while (j < b.length) push('added', b[j++]!)
  return segments
}

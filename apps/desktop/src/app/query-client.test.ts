import { describe, expect, it } from 'vitest'

import { ApiError, RequestTimeout } from '@/lib/api/errors'

import { createAppQueryClient, shouldRetry } from './query-client'

describe('shouldRetry', () => {
  it('gives up on client errors at once', () => {
    expect(shouldRetry(0, new ApiError(422, 'invalid'))).toBe(false)
  })

  it('retries server and network errors twice', () => {
    expect(shouldRetry(0, new ApiError(503, 'starting'))).toBe(true)
    expect(shouldRetry(1, new TypeError('Failed to fetch'))).toBe(true)
    expect(shouldRetry(2, new TypeError('Failed to fetch'))).toBe(false)
  })

  it('gives up on a timeout at once: the learner has waited long enough to see it', () => {
    expect(shouldRetry(0, new RequestTimeout(20_000))).toBe(false)
  })

  it('is the default for queries', () => {
    expect(createAppQueryClient().getDefaultOptions().queries?.retry).toBe(shouldRetry)
  })
})

import { describe, expect, it } from 'vitest'

import { ApiError } from '@/lib/api/errors'

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

  it('is the default for queries', () => {
    expect(createAppQueryClient().getDefaultOptions().queries?.retry).toBe(shouldRetry)
  })
})

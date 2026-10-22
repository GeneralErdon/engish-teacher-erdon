import { describe, expect, it, vi } from 'vitest'

import { fetchClient } from './client'
import { ApiError } from './errors'

describe('fetchClient', () => {
  it('throws ApiError for non-2xx answers, even without a JSON body', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html>', { status: 503 })))

    await expect(fetchClient.GET('/healthz')).rejects.toEqual(
      new ApiError(503, 'Request failed with HTTP 503'),
    )
  })

  it('returns data for 2xx answers', async () => {
    const health = { status: 'ok', service: 'api', version: '0.1.0' }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json(health)))

    const { data } = await fetchClient.GET('/healthz')

    expect(data).toEqual(health)
  })
})

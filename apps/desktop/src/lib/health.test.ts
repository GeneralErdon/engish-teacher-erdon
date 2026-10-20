import { describe, expect, it, vi } from 'vitest'

import { fetchHealth, isHealthResponse } from './health'

const healthy = { status: 'ok', service: 'api', version: '0.1.0' }

describe('isHealthResponse', () => {
  it('accepts the api and pron payloads', () => {
    expect(isHealthResponse(healthy)).toBe(true)
    expect(isHealthResponse({ ...healthy, service: 'pron' })).toBe(true)
  })

  it.each([null, 'ok', {}, { ...healthy, status: 'down' }, { ...healthy, version: 1 }])(
    'rejects %j',
    (value) => {
      expect(isHealthResponse(value)).toBe(false)
    },
  )
})

describe('fetchHealth', () => {
  it('calls /healthz on the backend and returns the parsed body', async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json(healthy))
    vi.stubGlobal('fetch', fetchMock)

    await expect(fetchHealth('http://localhost:8080')).resolves.toEqual(healthy)
    expect(fetchMock).toHaveBeenCalledWith('http://localhost:8080/healthz', { signal: null })
  })

  it('fails on HTTP errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 503 })))

    await expect(fetchHealth('http://x')).rejects.toThrow('HTTP 503')
  })

  it('fails on unexpected bodies', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ status: 'ok' })))

    await expect(fetchHealth('http://x')).rejects.toThrow('unexpected body')
  })
})

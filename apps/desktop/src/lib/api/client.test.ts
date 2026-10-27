import { afterEach, describe, expect, it, vi } from 'vitest'

import { fetchClient } from './client'
import { ApiError, RequestTimeout } from './errors'

/** `fetch` against an api that never answers: like the real one, it gives up when aborted. */
const silentApi = () =>
  vi.fn(
    (request: Request) =>
      new Promise<Response>((_resolve, reject) => {
        request.signal.addEventListener('abort', () => {
          reject(new DOMException('The operation was aborted.', 'AbortError'))
        })
      }),
  )

/** Whether `promise` has settled, without waiting for it. */
async function settled(promise: Promise<unknown>) {
  let done = false
  promise.then(
    () => (done = true),
    () => (done = true),
  )
  await Promise.resolve()
  await Promise.resolve()
  return done
}

describe('fetchClient', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

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

  it('gives up on a read the api has not answered within 20 s', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', silentApi())

    const read = fetchClient.GET('/healthz')
    const failure = expect(read).rejects.toThrow('The api did not answer within 20 s.')
    await vi.advanceTimersByTimeAsync(19_999)
    expect(await settled(read)).toBe(false)
    await vi.advanceTimersByTimeAsync(1)

    await failure
    await expect(read).rejects.toBeInstanceOf(RequestTimeout)
  })

  it('waits up to 90 s for anything but a read: the model test alone may take 60 s', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', silentApi())

    const test = fetchClient.POST('/v1/llm/test', {
      body: { kind: 'ollama', base_url: 'http://localhost:11434', model: 'm' },
    })
    const failure = expect(test).rejects.toThrow('The api did not answer within 90 s.')
    await vi.advanceTimersByTimeAsync(89_999)
    expect(await settled(test)).toBe(false)
    await vi.advanceTimersByTimeAsync(1)

    await failure
  })

  it('still lets the caller cancel: that is not a timeout', async () => {
    vi.stubGlobal('fetch', silentApi())
    const caller = new AbortController()

    const read = fetchClient.GET('/healthz', { signal: caller.signal })
    caller.abort()

    await expect(read).rejects.toMatchObject({ name: 'AbortError' })
  })
})

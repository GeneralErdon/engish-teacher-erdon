import createFetchClient, { type Middleware } from 'openapi-fetch'
import createQueryClient from 'openapi-react-query'

import type { components, paths } from '@/generated/api'
import { backendUrl } from '@/lib/platform'

import { RequestTimeout, toApiError } from './errors'

/** Schemas of the api (generated from its OpenAPI document by `just types`). */
export type Schemas = components['schemas']

/**
 * How long the api has to start answering before the UI gives up and says so, instead of
 * loading forever. Reads are quick; anything else may wait on a model (the model test alone
 * allows 60 s).
 */
const READ_TIMEOUT_MS = 20_000
const WRITE_TIMEOUT_MS = 90_000

/** `fetch`, given up after the method's timeout; the caller can still cancel it as usual. */
async function fetchInTime(request: Request): Promise<Response> {
  const ms = request.method === 'GET' ? READ_TIMEOUT_MS : WRITE_TIMEOUT_MS
  const timeout = new AbortController()
  const timer = setTimeout(() => {
    timeout.abort(new RequestTimeout(ms))
  }, ms)
  try {
    // Looked up on every request, not captured at import time, so tests can stub `fetch`.
    return await globalThis.fetch(
      new Request(request, { signal: AbortSignal.any([request.signal, timeout.signal]) }),
    )
  } catch (error) {
    // Some browsers reject with a plain AbortError rather than the signal's reason.
    throw timeout.signal.aborted ? timeout.signal.reason : error
  } finally {
    clearTimeout(timer)
  }
}

/**
 * Any non-2xx answer becomes a thrown `ApiError`, so callers and TanStack Query's error states
 * never branch on `error` versus `data`. The response is cloned: reading a body consumes it.
 */
const throwOnError: Middleware = {
  async onResponse({ response }) {
    if (response.ok) return response
    const body: unknown = await response
      .clone()
      .json()
      .catch(() => null)
    throw toApiError(response.status, body)
  },
}

export const fetchClient = createFetchClient<paths>({
  baseUrl: backendUrl(),
  fetch: fetchInTime,
})
fetchClient.use(throwOnError)

/** Typed TanStack Query hooks: `api.useQuery('get', '/healthz')`. */
export const api = createQueryClient(fetchClient)

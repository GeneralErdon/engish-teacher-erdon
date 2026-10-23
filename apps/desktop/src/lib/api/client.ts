import createFetchClient, { type Middleware } from 'openapi-fetch'
import createQueryClient from 'openapi-react-query'

import type { components, paths } from '@/generated/api'
import { backendUrl } from '@/lib/platform'

import { toApiError } from './errors'

/** Schemas of the api (generated from its OpenAPI document by `just types`). */
export type Schemas = components['schemas']

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
  // Looked up on every request, not captured at import time, so tests can stub `fetch`.
  fetch: (request) => globalThis.fetch(request),
})
fetchClient.use(throwOnError)

/** Typed TanStack Query hooks: `api.useQuery('get', '/healthz')`. */
export const api = createQueryClient(fetchClient)

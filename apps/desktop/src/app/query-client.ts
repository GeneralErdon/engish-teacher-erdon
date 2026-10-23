import { QueryClient } from '@tanstack/react-query'

import { ApiError } from '@/lib/api/errors'

const MAX_RETRIES = 2

/** Retry network failures and 5xx; a 4xx will not fix itself. */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status < 500) return false
  return failureCount < MAX_RETRIES
}

export function createAppQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        retry: shouldRetry,
        // The api is local: refetching on focus is cheap and keeps statuses honest.
        refetchOnWindowFocus: true,
      },
      mutations: { retry: false },
    },
  })
}

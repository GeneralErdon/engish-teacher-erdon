import { api } from '@/lib/api/client'

const POLL_MS = 15_000

/** The api's liveness, polled so the UI notices when it starts or stops. */
export function useHealth() {
  return api.useQuery('get', '/healthz', undefined, {
    refetchInterval: POLL_MS,
    retry: false,
    staleTime: 0,
  })
}

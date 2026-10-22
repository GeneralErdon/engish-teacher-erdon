import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api/client'

export const speechStatusQuery = api.queryOptions('get', '/v1/speech/status')

export function useSpeechStatus({ enabled = true } = {}) {
  return useQuery({ ...speechStatusQuery, enabled })
}

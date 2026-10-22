import { useQuery, useQueryClient } from '@tanstack/react-query'

import { api, type Schemas } from '@/lib/api/client'

export type ProviderInfo = Schemas['ProviderInfo']
export type ProviderKind = Schemas['ProviderKind']
export type LlmSettings = Schemas['LlmSettingsView']

/** The provider catalogue never changes while the api runs. */
export const providersQuery = api.queryOptions('get', '/v1/llm/providers', undefined, {
  staleTime: Infinity,
})
export const settingsQuery = api.queryOptions('get', '/v1/llm/settings')

export function useProviders({ enabled = true } = {}) {
  return useQuery({ ...providersQuery, enabled })
}

export function useLlmSettings({ enabled = true } = {}) {
  return useQuery({ ...settingsQuery, enabled })
}

/** Replace the cached settings with what a save or a reset returned (no refetch needed). */
export function useSetLlmSettings() {
  const queryClient = useQueryClient()
  return (settings: LlmSettings) => {
    queryClient.setQueryData(settingsQuery.queryKey, settings)
  }
}

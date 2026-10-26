import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'

import { api, fetchClient, type Schemas } from '@/lib/api/client'

export const DOWNLOAD_POLL_MS = 1000

export const speechStatusQuery = api.queryOptions('get', '/v1/speech/status')
export const speechSettingsQuery = api.queryOptions('get', '/v1/speech/settings')
export const speechModelsQuery = api.queryOptions('get', '/v1/speech/models')
export const voicesQuery = (model: string) =>
  api.queryOptions('get', '/v1/speech/voices', { params: { query: { model } } })

export function useSpeechStatus({ enabled = true } = {}) {
  return useQuery({ ...speechStatusQuery, enabled })
}

/**
 * The model catalogue. It refetches every second while a download runs, and when the last one
 * ends (finished, cancelled or failed) the settings and the readiness too: the api may have
 * activated the model.
 */
export function useSpeechModels() {
  const queryClient = useQueryClient()
  const query = useQuery({
    ...speechModelsQuery,
    refetchInterval: ({ state }) =>
      state.data?.models.some((model) => model.state === 'downloading') ? DOWNLOAD_POLL_MS : false,
  })
  const downloading = query.data?.models.some((model) => model.state === 'downloading') ?? false
  const was = useRef(false)
  useEffect(() => {
    if (was.current && !downloading) {
      void queryClient.invalidateQueries({ queryKey: speechSettingsQuery.queryKey })
      void queryClient.invalidateQueries({ queryKey: speechStatusQuery.queryKey })
    }
    was.current = downloading
  }, [downloading, queryClient])
  return query
}

/**
 * Save the speech settings; the answer replaces the cached settings, and the catalogue and the
 * readiness (of the models now in use) are re-read.
 */
export function useSaveSpeechSettings() {
  const queryClient = useQueryClient()
  return api.useMutation('put', '/v1/speech/settings', {
    onSuccess: (saved) => {
      queryClient.setQueryData(speechSettingsQuery.queryKey, saved)
      void queryClient.invalidateQueries({ queryKey: speechModelsQuery.queryKey })
      void queryClient.invalidateQueries({ queryKey: speechStatusQuery.queryKey })
    },
  })
}

/** Download, cancel and uninstall: after each, the catalogue and the settings are re-read. */
export function useModelActions() {
  const queryClient = useQueryClient()
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: speechModelsQuery.queryKey }),
      queryClient.invalidateQueries({ queryKey: speechSettingsQuery.queryKey }),
    ])
  const download = api.useMutation('post', '/v1/speech/models/{key}/download', {
    onSuccess: (models) => {
      queryClient.setQueryData(speechModelsQuery.queryKey, models)
      // The api now lists the model as pending when it will be activated.
      void queryClient.invalidateQueries({ queryKey: speechSettingsQuery.queryKey })
    },
  })
  const cancel = api.useMutation('delete', '/v1/speech/models/{key}/download', {
    onSuccess: refresh,
  })
  const uninstall = api.useMutation('delete', '/v1/speech/models/{key}', { onSuccess: refresh })
  return { download, cancel, uninstall }
}

/** A sample sentence in the chosen voice, played through the browser. */
export async function playPreview(body: Schemas['VoicePreview']): Promise<void> {
  const { data } = await fetchClient.POST('/v1/speech/preview', { body, parseAs: 'blob' })
  const url = URL.createObjectURL(data as Blob)
  const audio = new Audio(url)
  audio.addEventListener(
    'ended',
    () => {
      URL.revokeObjectURL(url)
    },
    { once: true },
  )
  await audio.play()
}

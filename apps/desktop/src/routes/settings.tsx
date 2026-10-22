import { createFileRoute } from '@tanstack/react-router'

import { SettingsPage } from '@/features/settings/settings-page'
import { providersQuery, settingsQuery } from '@/features/settings/use-llm'

const ignore = () => undefined

export const Route = createFileRoute('/settings')({
  // Warm the cache without blocking the page: it renders its own loading and error states.
  loader: ({ context: { queryClient } }) => {
    queryClient.query(providersQuery).catch(ignore)
    queryClient.query(settingsQuery).catch(ignore)
  },
  component: SettingsPage,
})

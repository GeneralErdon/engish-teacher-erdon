import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'

import { App } from '@/app/App'
import { createAppQueryClient } from '@/app/query-client'
import { createAppRouter } from '@/app/router'

import { fakeApi, type FakeApi } from './fake-api'

/** The whole app at `path`, against `api` (a fake backend), with retries off for speed. */
export function renderApp(path = '/', api: FakeApi = fakeApi()) {
  vi.stubGlobal('fetch', api.fetch)
  const queryClient = createAppQueryClient()
  queryClient.setDefaultOptions({
    queries: { retry: false, staleTime: 30_000 },
    mutations: { retry: false },
  })
  const router = createAppRouter(queryClient, createMemoryHistory({ initialEntries: [path] }))
  const user = userEvent.setup()
  const view = render(<App queryClient={queryClient} router={router} />)
  return { ...view, api, router, queryClient, user, screen }
}

import type { QueryClient } from '@tanstack/react-query'
import { createHashHistory, createRouter, type RouterHistory } from '@tanstack/react-router'

import { routeTree } from '@/generated/routeTree.gen'

export interface RouterContext {
  queryClient: QueryClient
}

/**
 * Hash history (`#/settings`): the UI is served from `tauri://localhost`, from the api's static
 * files and from Vite, and none of them needs to know the app's routes to reload a page.
 */
export function createAppRouter(
  queryClient: QueryClient,
  history: RouterHistory = createHashHistory(),
) {
  return createRouter({
    routeTree,
    history,
    context: { queryClient },
    // Load a page's code and data while the pointer rests on its link.
    defaultPreload: 'intent',
    // TanStack Query owns caching; the router always asks it.
    defaultPreloadStaleTime: 0,
    scrollRestoration: true,
  })
}

declare module '@tanstack/react-router' {
  interface Register {
    router: ReturnType<typeof createAppRouter>
  }
}

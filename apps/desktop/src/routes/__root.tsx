import { createRootRouteWithContext } from '@tanstack/react-router'

import type { RouterContext } from '@/app/router'
import { AppShell } from '@/components/layout/app-shell'
import { NotFound } from '@/components/not-found'

export const Route = createRootRouteWithContext<RouterContext>()({
  component: AppShell,
  notFoundComponent: NotFound,
})

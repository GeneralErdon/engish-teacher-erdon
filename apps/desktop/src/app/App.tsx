import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { RouterProvider } from '@tanstack/react-router'
import { LazyMotion, MotionConfig } from 'motion/react'
import { useState } from 'react'

import { createAppQueryClient } from './query-client'
import { createAppRouter } from './router'

const loadMotionFeatures = () => import('./motion-features').then((module) => module.default)

export interface AppProps {
  /** Tests inject their own (memory history, fresh cache). */
  queryClient?: QueryClient
  router?: ReturnType<typeof createAppRouter>
}

export function App(props: AppProps) {
  const [queryClient] = useState(() => props.queryClient ?? createAppQueryClient())
  const [router] = useState(() => props.router ?? createAppRouter(queryClient))

  return (
    <QueryClientProvider client={queryClient}>
      {/* `strict`: only the lightweight `m.*` components may be used. `reducedMotion`: honour
          the OS setting, keeping opacity fades but dropping movement. */}
      <LazyMotion features={loadMotionFeatures} strict>
        <MotionConfig reducedMotion="user">
          <RouterProvider router={router} />
        </MotionConfig>
      </LazyMotion>
    </QueryClientProvider>
  )
}

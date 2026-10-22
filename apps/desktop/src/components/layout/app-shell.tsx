import { Outlet, useRouterState } from '@tanstack/react-router'
import { m } from 'motion/react'

import { Brand } from '@/components/brand'
import { ThemeToggle } from '@/components/theme-toggle'
import { BackendStatus } from '@/features/status/backend-status'

import { NAV_ITEMS } from './nav-items'
import { NavLink } from './nav-link'

const EASE_OUT = [0.22, 1, 0.36, 1] as const

/**
 * Responsive frame: a sidebar from `md` up; below it, a top bar and a thumb-friendly tab bar.
 * Pages fade and rise in on navigation (opacity and transform only: GPU-composited).
 */
export function AppShell() {
  const pathname = useRouterState({ select: (state) => state.location.pathname })

  return (
    <div className="min-h-dvh md:grid md:grid-cols-[16rem_1fr]">
      <aside className="border-sidebar-border bg-sidebar sticky top-0 hidden h-dvh flex-col gap-8 border-r p-5 backdrop-blur-xl md:flex">
        <Brand />
        <nav aria-label="Main" className="flex flex-col gap-1">
          {NAV_ITEMS.map((item) => (
            <NavLink key={item.to} item={item} variant="sidebar" />
          ))}
        </nav>
        <div className="mt-auto flex items-center justify-between gap-2">
          <BackendStatus />
          <ThemeToggle />
        </div>
      </aside>

      <div className="flex min-h-dvh min-w-0 flex-col">
        <header className="border-sidebar-border bg-sidebar sticky top-0 z-20 flex items-center justify-between gap-3 border-b px-4 py-3 backdrop-blur-xl md:hidden">
          <Brand />
          <ThemeToggle />
        </header>

        <main className="flex-1 px-4 pt-6 pb-28 sm:px-6 md:px-10 md:pt-10 md:pb-12">
          <div className="mx-auto w-full max-w-5xl">
            <m.div
              key={pathname}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.35, ease: EASE_OUT }}
            >
              <Outlet />
            </m.div>
          </div>
        </main>
      </div>

      <nav
        aria-label="Main"
        className="border-sidebar-border bg-sidebar fixed inset-x-0 bottom-0 z-20 flex gap-1 border-t px-3 pt-1.5 pb-[max(0.5rem,env(safe-area-inset-bottom))] backdrop-blur-xl md:hidden"
      >
        {NAV_ITEMS.map((item) => (
          <NavLink key={item.to} item={item} variant="tabs" />
        ))}
      </nav>
    </div>
  )
}

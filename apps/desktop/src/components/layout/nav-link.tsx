import { Link } from '@tanstack/react-router'
import { m } from 'motion/react'

import { cn } from '@/lib/utils'

import type { NavItem } from './nav-items'

const SPRING = { type: 'spring', stiffness: 500, damping: 40 } as const

/**
 * One navigation entry. The highlight behind the active entry is a shared layout element
 * (`layoutId`), so it slides from the old entry to the new one instead of blinking.
 */
export function NavLink({ item, variant }: { item: NavItem; variant: 'sidebar' | 'tabs' }) {
  const Icon = item.icon
  return (
    <Link
      to={item.to}
      activeOptions={{ exact: true }}
      className={cn(
        'focus-visible:ring-ring/50 relative flex items-center rounded-xl outline-none transition-colors focus-visible:ring-[3px]',
        variant === 'sidebar'
          ? 'text-sidebar-foreground hover:text-foreground gap-3 px-3 py-2.5 text-sm font-medium'
          : 'text-muted-foreground flex-1 flex-col justify-center gap-1 py-2 text-[11px] font-medium',
        'data-[status=active]:text-sidebar-accent-foreground',
      )}
    >
      {({ isActive }) => (
        <>
          {isActive && (
            <m.span
              layoutId={`nav-highlight-${variant}`}
              transition={SPRING}
              aria-hidden="true"
              className="bg-sidebar-accent absolute inset-0 rounded-xl"
            />
          )}
          <Icon className="relative size-5" aria-hidden="true" />
          <span className="relative">{item.label}</span>
        </>
      )}
    </Link>
  )
}

import { House, Settings2, type LucideIcon } from 'lucide-react'

export interface NavItem {
  to: '/' | '/settings'
  label: string
  icon: LucideIcon
}

export const NAV_ITEMS: readonly NavItem[] = [
  { to: '/', label: 'Home', icon: House },
  { to: '/settings', label: 'Settings', icon: Settings2 },
]

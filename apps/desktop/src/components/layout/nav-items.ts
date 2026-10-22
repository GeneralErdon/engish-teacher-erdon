import { House, MessagesSquare, Settings2, type LucideIcon } from 'lucide-react'

export interface NavItem {
  to: '/' | '/practice' | '/settings'
  label: string
  icon: LucideIcon
}

export const NAV_ITEMS: readonly NavItem[] = [
  { to: '/', label: 'Home', icon: House },
  { to: '/practice', label: 'Practice', icon: MessagesSquare },
  { to: '/settings', label: 'Settings', icon: Settings2 },
]

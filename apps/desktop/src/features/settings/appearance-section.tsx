import { Monitor, Moon, Sun } from 'lucide-react'

import { SegmentedControl, type SegmentedOption } from '@/components/segmented-control'
import { useTheme, type ThemePreference } from '@/lib/theme'

const OPTIONS: readonly SegmentedOption<ThemePreference>[] = [
  { value: 'system', label: 'System', icon: Monitor },
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
]

export function AppearanceSection() {
  const { preference, setPreference } = useTheme()
  return (
    <SegmentedControl label="Theme" options={OPTIONS} value={preference} onChange={setPreference} />
  )
}

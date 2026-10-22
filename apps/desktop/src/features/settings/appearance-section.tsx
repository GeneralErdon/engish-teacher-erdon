import { Monitor, Moon, Sun, type LucideIcon } from 'lucide-react'
import { m } from 'motion/react'
import { RadioGroup as RadioGroupPrimitive } from 'radix-ui'

import { useTheme, type ThemePreference } from '@/lib/theme'
import { cn } from '@/lib/utils'

const OPTIONS: readonly { value: ThemePreference; label: string; icon: LucideIcon }[] = [
  { value: 'system', label: 'System', icon: Monitor },
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
]

/** A segmented control; the highlight slides between options (shared layout animation). */
export function AppearanceSection() {
  const { preference, setPreference } = useTheme()

  return (
    <RadioGroupPrimitive.Root
      aria-label="Theme"
      value={preference}
      onValueChange={(value) => {
        setPreference(value as ThemePreference)
      }}
      className="bg-muted inline-grid grid-cols-3 gap-1 rounded-xl p-1"
    >
      {OPTIONS.map(({ value, label, icon: Icon }) => (
        <RadioGroupPrimitive.Item
          key={value}
          value={value}
          className={cn(
            'focus-visible:ring-ring/50 text-muted-foreground relative flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium outline-none focus-visible:ring-[3px]',
            'data-[state=checked]:text-foreground',
          )}
        >
          {preference === value && (
            <m.span
              layoutId="theme-highlight"
              transition={{ type: 'spring', stiffness: 500, damping: 40 }}
              aria-hidden="true"
              className="bg-background absolute inset-0 rounded-lg shadow-sm"
            />
          )}
          <Icon className="relative size-4" aria-hidden="true" />
          <span className="relative">{label}</span>
        </RadioGroupPrimitive.Item>
      ))}
    </RadioGroupPrimitive.Root>
  )
}

import type { LucideIcon } from 'lucide-react'
import { m } from 'motion/react'
import { RadioGroup as RadioGroupPrimitive } from 'radix-ui'

import { cn } from '@/lib/utils'

export interface SegmentedOption<T extends string> {
  value: T
  label: string
  icon?: LucideIcon
}

/**
 * A row of mutually exclusive options (a radio group: arrow keys move between them). The
 * highlight slides to the chosen option as a shared layout element.
 */
export function SegmentedControl<T extends string>({
  label,
  options,
  value,
  onChange,
  disabled,
  className,
}: {
  /** Accessible name; also keys the sliding highlight, so it must be unique on the page. */
  label: string
  options: readonly SegmentedOption<T>[]
  value: T
  onChange: (value: T) => void
  disabled?: boolean
  className?: string
}) {
  return (
    <RadioGroupPrimitive.Root
      aria-label={label}
      value={value}
      disabled={disabled}
      onValueChange={(next) => {
        onChange(next as T)
      }}
      className={cn('bg-muted inline-flex flex-wrap gap-1 rounded-xl p-1', className)}
    >
      {options.map(({ value: option, label: optionLabel, icon: Icon }) => (
        <RadioGroupPrimitive.Item
          key={option}
          value={option}
          className={cn(
            'focus-visible:ring-ring/50 text-muted-foreground relative flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium outline-none focus-visible:ring-[3px] disabled:opacity-60',
            'data-[state=checked]:text-foreground',
          )}
        >
          {value === option && (
            <m.span
              layoutId={`segmented-${label}`}
              transition={{ type: 'spring', stiffness: 500, damping: 40 }}
              aria-hidden="true"
              className="bg-background absolute inset-0 rounded-lg shadow-sm"
            />
          )}
          {Icon && <Icon className="relative size-4" aria-hidden="true" />}
          <span className="relative">{optionLabel}</span>
        </RadioGroupPrimitive.Item>
      ))}
    </RadioGroupPrimitive.Root>
  )
}

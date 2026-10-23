import { AudioLines } from 'lucide-react'

import { cn } from '@/lib/utils'

export function Brand({ className }: { className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-2.5', className)}>
      <span
        aria-hidden="true"
        className="from-primary to-highlight text-primary-foreground grid size-9 place-items-center rounded-xl bg-linear-to-br shadow-md shadow-primary/25"
      >
        <AudioLines className="size-5" />
      </span>
      <span className="font-display text-lg font-semibold tracking-tight">voice-tutor</span>
    </span>
  )
}

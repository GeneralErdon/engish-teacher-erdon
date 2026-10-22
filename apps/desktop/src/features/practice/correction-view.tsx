import { CheckCircle2, Loader2, TriangleAlert } from 'lucide-react'
import { m } from 'motion/react'

import { cn } from '@/lib/utils'

import { wordDiff } from './diff'
import type { Correction } from './use-conversation'

/**
 * Tandem-style feedback under the learner's message: the wrong words struck through in red,
 * the right ones in green, then one short explanation per mistake.
 */
export function CorrectionView({
  text,
  correction,
}: {
  text: string
  correction: Correction | undefined
}) {
  if (!correction) {
    return (
      <p className="text-muted-foreground flex items-center gap-1.5 text-xs">
        <Loader2 className="size-3 animate-spin" aria-hidden="true" /> Checking your English…
      </p>
    )
  }
  if (correction.items.length === 0) {
    return (
      <p className="text-success flex items-center gap-1.5 text-xs font-medium">
        <CheckCircle2 className="size-3.5" aria-hidden="true" /> Looks good
      </p>
    )
  }
  return (
    <m.div
      initial={{ opacity: 0, y: -4 }}
      animate={{ opacity: 1, y: 0 }}
      aria-label="Correction"
      className="bg-card w-full rounded-xl border p-3 text-sm shadow-xs"
    >
      <p className="leading-relaxed">
        {wordDiff(text, correction.corrected).map((segment, index) => (
          <span
            key={index}
            className={cn(
              segment.kind === 'removed' &&
                'text-destructive decoration-destructive/70 line-through decoration-2',
              segment.kind === 'added' && 'text-success font-semibold',
            )}
          >
            {segment.kind === 'removed' && <span className="sr-only">remove: </span>}
            {segment.kind === 'added' && <span className="sr-only">add: </span>}
            {segment.text}{' '}
          </span>
        ))}
      </p>
      <ul className="mt-2 flex flex-col gap-1.5 border-t pt-2">
        {correction.items.map((item, index) => (
          <li key={index} className="text-muted-foreground flex gap-2 text-xs leading-relaxed">
            <TriangleAlert className="text-warning mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
            <span>
              <span className="text-foreground font-medium">
                {item.original} → {item.suggestion}
              </span>{' '}
              {item.explanation}
            </span>
          </li>
        ))}
      </ul>
    </m.div>
  )
}

import { useEffect, useRef } from 'react'

import { cn } from '@/lib/utils'

import type { CallPhase } from './use-call'

/** How fast the orb follows the level (0..1 per frame): smooth, but not sluggish. */
const EASING = 0.25
/** Speech RMS rarely passes 0.25: scale it so a normal voice fills the range. */
const GAIN = 4

/**
 * Call mode's orb: a living gradient that grows with whoever is talking. `level` is read on
 * every animation frame and written to a CSS variable, so the animation never re-renders React.
 */
export function Orb({
  phase,
  level,
  className,
}: {
  phase: CallPhase
  level: () => number
  className?: string
}) {
  const orb = useRef<HTMLDivElement>(null)
  const read = useRef(level)

  useEffect(() => {
    read.current = level
  })

  useEffect(() => {
    let frame = 0
    let smooth = 0
    const tick = () => {
      smooth += (Math.min(1, read.current() * GAIN) - smooth) * EASING
      orb.current?.style.setProperty('--orb-level', smooth.toFixed(3))
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => {
      cancelAnimationFrame(frame)
    }
  }, [])

  return <div ref={orb} data-phase={phase} aria-hidden="true" className={cn('orb', className)} />
}

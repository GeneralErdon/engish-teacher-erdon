import { cn } from '@/lib/utils'

const BARS = [0.35, 0.6, 0.9, 0.55, 1, 0.7, 0.45, 0.8, 0.5, 0.95, 0.65, 0.4, 0.75, 0.55, 0.3]

/**
 * Decorative "voice" bars. Pure CSS (transform only, so the compositor does the work) and
 * still for people who ask for reduced motion.
 */
export function VoiceWave({ className }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={cn('pointer-events-none flex items-center gap-1.5', className)}
    >
      {BARS.map((height, index) => (
        <span
          key={index}
          className="from-primary to-highlight h-full flex-1 origin-center rounded-full bg-linear-to-t motion-safe:animate-voice-wave"
          style={{
            transform: `scaleY(${String(height)})`,
            animationDelay: `${String(index * 90)}ms`,
          }}
        />
      ))}
    </div>
  )
}

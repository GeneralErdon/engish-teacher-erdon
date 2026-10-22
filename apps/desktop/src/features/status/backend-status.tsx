import { cn } from '@/lib/utils'

import { useHealth } from './use-health'

/** A compact "API online · v0.1.0" pill with a live dot. */
export function BackendStatus({ className }: { className?: string }) {
  const health = useHealth()
  const state = health.isSuccess ? 'online' : health.isError ? 'offline' : 'checking'

  return (
    <div
      role="status"
      aria-live="polite"
      data-state={state}
      className={cn(
        'text-muted-foreground inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs',
        className,
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          'size-2 rounded-full',
          state === 'online' && 'bg-success shadow-[0_0_0_3px] shadow-success/20',
          state === 'offline' && 'bg-destructive',
          state === 'checking' && 'bg-muted-foreground motion-safe:animate-pulse',
        )}
      />
      {state === 'online' && <span>API online · v{health.data?.version}</span>}
      {state === 'offline' && <span>API offline</span>}
      {state === 'checking' && <span>Checking the API…</span>}
    </div>
  )
}

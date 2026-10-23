import { useId, type ReactNode } from 'react'

import { Label } from '@/components/ui/label'

/** Spread onto the control so the label, hint and error point at it. */
export interface ControlProps {
  id: string
  'aria-invalid': true | undefined
  'aria-describedby': string | undefined
}

/**
 * Label, control, hint and error, wired for screen readers: `children` receives the props that
 * give the control its id and point `aria-describedby` at the hint and the error.
 */
export function Field({
  label,
  action,
  hint,
  error,
  children,
}: {
  label: ReactNode
  /** Rendered at the end of the label row (e.g. a "Load models" button). */
  action?: ReactNode
  hint?: ReactNode
  error?: string | undefined
  children: (control: ControlProps) => ReactNode
}) {
  const id = useId()
  const hintId = `${id}-hint`
  const errorId = `${id}-error`
  const describedBy = [hint && hintId, error && errorId].filter(Boolean).join(' ') || undefined

  return (
    <div className="flex flex-col gap-2">
      <div className="flex min-h-8 items-center justify-between gap-2">
        <Label htmlFor={id}>{label}</Label>
        {action}
      </div>
      {children({
        id,
        'aria-invalid': error ? true : undefined,
        'aria-describedby': describedBy,
      })}
      {hint && (
        <p id={hintId} className="text-muted-foreground text-xs">
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} role="alert" className="text-destructive text-xs font-medium">
          {error}
        </p>
      )}
    </div>
  )
}

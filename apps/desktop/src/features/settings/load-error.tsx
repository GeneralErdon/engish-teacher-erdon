import { RotateCw } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { errorMessage } from '@/lib/api/errors'

/** Something could not load: why, and a button to ask the api again. */
export function LoadError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return (
    <div role="alert" className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm">
      <span className="text-destructive">{errorMessage(error)}</span>
      <Button size="sm" variant="outline" onClick={onRetry}>
        <RotateCw /> Try again
      </Button>
    </div>
  )
}

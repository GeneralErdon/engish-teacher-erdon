import { CheckCircle2, RotateCw, TriangleAlert } from 'lucide-react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { errorMessage } from '@/lib/api/errors'
import { cn } from '@/lib/utils'

import { useSpeechStatus } from './use-speech'

function Command({ children }: { children: string }) {
  return (
    <pre className="bg-muted text-foreground overflow-x-auto rounded-md px-3 py-2 font-mono text-xs">
      {children}
    </pre>
  )
}

/** Is local speech recognition (Speaches) ready? If not, the exact steps to get there. */
export function SpeechSection() {
  const speech = useSpeechStatus()

  if (!speech.data) {
    return speech.isError ? (
      <p role="alert" className="text-destructive text-sm">
        {errorMessage(speech.error)}
      </p>
    ) : (
      <Skeleton aria-label="Loading" className="h-20 rounded-xl" />
    )
  }

  const status = speech.data
  return (
    <div className="flex flex-col gap-4">
      {status.model_ready ? (
        <p className="text-success flex items-center gap-2 text-sm font-medium">
          <CheckCircle2 className="size-4" aria-hidden="true" /> Ready: {status.model}
        </p>
      ) : (
        <Alert>
          <TriangleAlert className="text-warning" />
          <AlertTitle>{status.detail ?? 'Speech recognition is not ready.'}</AlertTitle>
          <AlertDescription className="flex w-full flex-col gap-2">
            {!status.reachable && (
              <>
                <span>Start the speech recognition server (Speaches, on your CPU):</span>
                <Command>docker compose --profile cpu up -d stt-cpu</Command>
              </>
            )}
            <span>{status.reachable ? 'Download' : 'Then download'} the model once:</span>
            <Command>{`SPEACHES_BASE_URL=http://localhost:8000 uvx speaches-cli model download ${status.model}`}</Command>
          </AlertDescription>
        </Alert>
      )}
      <div className="text-muted-foreground flex flex-wrap items-center gap-3 text-xs">
        <code className="bg-muted rounded-md px-2 py-1">{status.base_url}</code>
        <Button
          size="sm"
          variant="outline"
          disabled={speech.isFetching}
          onClick={() => void speech.refetch()}
        >
          <RotateCw className={cn(speech.isFetching && 'animate-spin')} /> Check again
        </Button>
      </div>
    </div>
  )
}

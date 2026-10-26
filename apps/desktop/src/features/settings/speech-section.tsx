import { CheckCircle2, CircleDashed, RotateCw, TriangleAlert } from 'lucide-react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import type { Schemas } from '@/lib/api/client'
import { errorMessage } from '@/lib/api/errors'
import { cn } from '@/lib/utils'

import { useSpeechStatus } from './use-speech'
import { VoiceSettings } from './voice-settings'

type ModelStatus = Schemas['ModelStatus']

function Command({ children }: { children: string }) {
  return (
    <pre className="bg-muted text-foreground overflow-x-auto rounded-md px-3 py-2 font-mono text-xs">
      {children}
    </pre>
  )
}

/** Readiness first, then the choice of models, voice and turn length. */
export function SpeechSection() {
  return (
    <div className="flex flex-col gap-6">
      <Readiness />
      <VoiceSettings />
    </div>
  )
}

/**
 * Are local speech recognition and the tutor's voice ready? Both run in Speaches; if something
 * is missing, the exact steps to get there.
 */
function Readiness() {
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

  const { recognition, synthesis } = speech.data
  const missing = [recognition, synthesis].filter((status) => !status.model_ready)
  const stopped = missing.some((status) => !status.reachable)
  const servers = [...new Set([recognition.base_url, synthesis.base_url])]
  return (
    <div className="flex flex-col gap-4">
      <ul className="flex flex-col gap-2">
        <ModelRow label="Speech recognition" status={recognition} />
        <ModelRow label="Tutor's voice" status={synthesis} />
      </ul>
      {missing.length > 0 && (
        <Alert>
          <TriangleAlert className="text-warning" />
          <AlertTitle>One-time setup</AlertTitle>
          <AlertDescription className="flex w-full flex-col gap-2">
            <span>
              {stopped
                ? 'Start Speaches, which runs both on your machine. The first start downloads the models (~700 MB) and waits until they are ready:'
                : 'Run this again: it downloads what is missing.'}
            </span>
            <Command>just voice</Command>
            {!stopped && (
              <>
                <span>Or, on a Speaches you started yourself:</span>
                {missing.map((status) => (
                  <Command key={status.model}>
                    {`SPEACHES_BASE_URL=http://localhost:8000 uvx speaches-cli model download ${status.model}`}
                  </Command>
                ))}
              </>
            )}
          </AlertDescription>
        </Alert>
      )}
      <div className="text-muted-foreground flex flex-wrap items-center gap-3 text-xs">
        {servers.map((url) => (
          <code key={url} className="bg-muted rounded-md px-2 py-1">
            {url}
          </code>
        ))}
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

function ModelRow({ label, status }: { label: string; status: ModelStatus }) {
  return (
    <li className="flex items-start gap-2 text-sm">
      {status.model_ready ? (
        <CheckCircle2 className="text-success mt-0.5 size-4 shrink-0" aria-label="Ready" />
      ) : (
        <CircleDashed className="text-warning mt-0.5 size-4 shrink-0" aria-label="Not ready" />
      )}
      <span className="flex flex-col">
        <span className="font-medium">{label}</span>
        <span className="text-muted-foreground break-all">
          {status.model_ready ? status.model : (status.detail ?? 'Not ready.')}
        </span>
      </span>
    </li>
  )
}

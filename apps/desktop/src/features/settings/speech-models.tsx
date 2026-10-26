import { Download, Loader2, X } from 'lucide-react'
import { RadioGroup as RadioGroupPrimitive } from 'radix-ui'
import { useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { Schemas } from '@/lib/api/client'
import { errorMessage } from '@/lib/api/errors'
import { cn } from '@/lib/utils'

import { useModelActions } from './use-speech'

type Model = Schemas['SpeechModel']
type Kind = Schemas['SpeechKind']

const MB = 1_000_000

/** "330 MB", or nothing for a model from the configuration, whose size the catalogue lacks. */
const size = (model: Model) => (model.approx_mb > 0 ? `${String(model.approx_mb)} MB` : null)

/**
 * The models of one kind as selectable rows. Choosing an installed one uses it; choosing one
 * that is not installed downloads it, and the api activates it when the download finishes.
 */
export function ModelList({
  label,
  kind,
  models,
  manageable,
  pending,
  disabled = false,
  onUse,
}: {
  /** Accessible name of the radio group. */
  label: string
  kind: Kind
  models: readonly Model[]
  /** False when the api cannot reach the models folder: the list is read-only. */
  manageable: boolean
  /** Model ids that will be used when their download finishes. */
  pending: readonly string[]
  /** No model can be chosen meanwhile (a settings save is running). */
  disabled?: boolean
  onUse: (model: Model) => void
}) {
  const actions = useModelActions()
  const rows = models.filter((model) => model.kind === kind)
  const selected = rows.find((model) => model.selected)
  const error = [actions.download, actions.cancel, actions.uninstall].find((m) => m.isError)?.error

  // A model that is not installed is only proposed: arrowing over rows must not start downloads.
  const [proposed, setProposed] = useState<string | null>(null)
  const proposal = rows.find((model) => model.key === proposed && model.state === 'available')

  const choose = (model: Model) => {
    if (model.state === 'installed') {
      setProposed(null)
      onUse(model)
    } else if (manageable) setProposed(model.key)
  }

  return (
    <div className="flex flex-col gap-2">
      <RadioGroupPrimitive.Root
        aria-label={label}
        disabled={disabled}
        value={proposal?.key ?? selected?.key ?? ''}
        onValueChange={(key) => {
          const model = rows.find((row) => row.key === key)
          if (model) choose(model)
        }}
        className="flex flex-col gap-2"
      >
        {rows.map((model) => (
          <ModelRow
            key={model.key}
            model={model}
            manageable={manageable}
            pending={pending.includes(model.model_id)}
            disabled={disabled}
            actions={actions}
            onUse={onUse}
            proposed={proposal?.key === model.key}
            onDismiss={() => {
              setProposed(null)
            }}
          />
        ))}
      </RadioGroupPrimitive.Root>
      {!manageable && (
        <p className="text-muted-foreground text-xs">
          Models cannot be installed or removed from here with this speech server. Pick among the
          ones it has.
        </p>
      )}
      {error && (
        <p role="alert" className="text-destructive text-xs">
          {errorMessage(error)}
        </p>
      )}
    </div>
  )
}

function ModelRow({
  model,
  manageable,
  pending,
  disabled,
  actions,
  onUse,
  proposed,
  onDismiss,
}: {
  model: Model
  manageable: boolean
  pending: boolean
  disabled: boolean
  actions: ReturnType<typeof useModelActions>
  onUse: (model: Model) => void
  /** The row is picked but not yet confirmed for download. */
  proposed: boolean
  onDismiss: () => void
}) {
  const [confirming, setConfirming] = useState(false)
  const key = { params: { path: { key: model.key } } }
  const downloading = model.state === 'downloading'
  const installed = model.state === 'installed'
  const mb = size(model)
  const titleId = `model-${model.key}`
  const hintId = `${titleId}-hint`

  return (
    <div
      className={cn(
        'flex flex-col gap-2 rounded-lg border p-3 text-sm',
        model.selected && 'border-primary',
      )}
    >
      <div className="flex items-start gap-3">
        <RadioGroupPrimitive.Item
          value={model.key}
          disabled={downloading || (!installed && !manageable)}
          aria-labelledby={titleId}
          aria-describedby={hintId}
          className="border-input focus-visible:ring-ring/50 data-[state=checked]:border-primary mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border outline-none focus-visible:ring-[3px] disabled:opacity-50"
        >
          <RadioGroupPrimitive.Indicator className="bg-primary size-2 rounded-full" />
        </RadioGroupPrimitive.Item>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <span id={titleId} className="font-medium">
              {model.label}
            </span>
            {model.default && <Badge variant="secondary">Default</Badge>}
            {model.selected && <Badge>In use</Badge>}
            <span className="text-muted-foreground text-xs">
              {[
                mb,
                model.kind === 'recognition' &&
                  (model.english_only ? 'English only' : 'Multilingual'),
              ]
                .filter(Boolean)
                .join(' · ')}
            </span>
          </div>
          <span id={hintId} className="text-muted-foreground text-xs">
            {model.hint}
          </span>
          {model.ms_per_audio_s !== null && (
            <span className="text-muted-foreground text-xs">
              Measured here: {Math.round(model.ms_per_audio_s)} ms per second of audio
            </span>
          )}
          {pending && <span className="text-xs">Will be used when the download finishes</span>}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {installed && !model.selected && (
            <Button
              size="sm"
              variant="outline"
              disabled={disabled}
              onClick={() => {
                onUse(model)
              }}
            >
              Use
            </Button>
          )}
          {!installed && !downloading && manageable && !proposed && (
            <Button
              size="sm"
              variant="outline"
              disabled={actions.download.isPending}
              onClick={() => {
                actions.download.mutate({ ...key, body: { activate: false } })
              }}
            >
              <Download /> {mb ? `Download (${mb})` : 'Download'}
            </Button>
          )}
          {downloading && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                actions.cancel.mutate(key)
              }}
            >
              <X /> Cancel
            </Button>
          )}
          {installed && manageable && !model.default && !model.selected && !confirming && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setConfirming(true)
              }}
            >
              Uninstall
            </Button>
          )}
        </div>
      </div>
      {proposed && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span>{mb ? `Download ${mb} and use it?` : 'Download and use it?'}</span>
          <Button
            size="xs"
            disabled={actions.download.isPending}
            onClick={() => {
              actions.download.mutate({ ...key, body: { activate: true } })
              onDismiss()
            }}
          >
            Download
          </Button>
          <Button size="xs" variant="outline" onClick={onDismiss}>
            Cancel
          </Button>
        </div>
      )}
      {downloading && <Progress label={model.label} progress={model.download} />}
      {confirming && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span>Remove {model.approx_mb} MB?</span>
          <Button
            size="xs"
            variant="destructive"
            disabled={actions.uninstall.isPending}
            onClick={() => {
              actions.uninstall.mutate(key)
              setConfirming(false)
            }}
          >
            Remove
          </Button>
          <Button
            size="xs"
            variant="outline"
            onClick={() => {
              setConfirming(false)
            }}
          >
            Keep
          </Button>
        </div>
      )}
    </div>
  )
}

function Progress({
  label,
  progress,
}: {
  label: string
  progress: Schemas['SpeechModel']['download']
}) {
  const percent =
    progress?.total_bytes && progress.total_bytes > 0
      ? Math.min(100, Math.round((progress.done_bytes / progress.total_bytes) * 100))
      : null
  return (
    <div className="flex items-center gap-2">
      <div
        role="progressbar"
        aria-label={
          percent === null ? `Downloading ${label}` : `Downloading ${label}: ${String(percent)}%`
        }
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent ?? undefined}
        className="bg-muted relative h-2 flex-1 overflow-hidden rounded-full"
      >
        <div
          className={cn(
            'bg-primary h-full rounded-full transition-[width]',
            percent === null && 'w-1/3 animate-pulse',
          )}
          style={percent === null ? undefined : { width: `${String(percent)}%` }}
        />
      </div>
      <span className="text-muted-foreground flex items-center gap-1 text-xs tabular-nums">
        {percent === null ? (
          <>
            <Loader2 className="size-3 animate-spin" aria-hidden="true" /> Starting…
          </>
        ) : (
          `${String(percent)}% · ${String(Math.round((progress?.done_bytes ?? 0) / MB))} MB`
        )}
      </span>
    </div>
  )
}

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Loader2, TriangleAlert } from 'lucide-react'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Skeleton } from '@/components/ui/skeleton'
import type { Schemas } from '@/lib/api/client'
import { errorMessage } from '@/lib/api/errors'

import { ModelList } from './speech-models'
import { TurnLength } from './turn-length'
import {
  speechSettingsQuery,
  useSaveSpeechSettings,
  useSpeechModels,
  voicesQuery,
} from './use-speech'
import { VoicePicker } from './voice-picker'

type Model = Schemas['SpeechModel']
type Settings = Schemas['SpeechSettings']

const KIND_NAMES = { recognition: 'speech recognition model', voice: "tutor's voice model" }

/** Which models listen and speak, how long a turn can be, and the voice. Saved at once. */
export function VoiceSettings() {
  const queryClient = useQueryClient()
  const settings = useQuery(speechSettingsQuery)
  const catalogue = useSpeechModels()
  const save = useSaveSpeechSettings()
  const voices = useQuery({
    ...voicesQuery(settings.data?.tts_model ?? ''),
    enabled: settings.data !== undefined,
  })

  if (!settings.data || !catalogue.data) {
    return settings.isError || catalogue.isError ? (
      <p role="alert" className="text-destructive text-sm">
        {errorMessage(settings.isError ? settings.error : catalogue.error)}
      </p>
    ) : (
      <Skeleton aria-label="Loading voice settings" className="h-24 rounded-xl" />
    )
  }

  const view = settings.data
  const { models, last_error: lastError } = catalogue.data
  const current: Settings = {
    stt_model: view.stt_model,
    tts_model: view.tts_model,
    tts_voice: view.tts_voice,
    tts_speed: view.tts_speed,
    max_turn_s: view.max_turn_s,
  }
  const update = (change: Partial<Settings>) => {
    save.mutate({ body: { ...current, ...change } })
  }

  const chooseModel = async (model: Model) => {
    if (model.kind === 'recognition') {
      update({ stt_model: model.model_id })
      return
    }
    // Keep the voice if the new model has it, else its first: the api re-validates anyway.
    const ids = await queryClient
      .query(voicesQuery(model.model_id))
      .then((list) => list.map((voice) => voice.id))
      .catch((): string[] => [])
    update({
      tts_model: model.model_id,
      tts_voice: ids.includes(view.tts_voice) ? view.tts_voice : (ids[0] ?? view.tts_voice),
    })
  }

  return (
    <div className="flex flex-col gap-6">
      {lastError && (
        <Alert variant="destructive">
          <TriangleAlert />
          <AlertDescription>{lastError}</AlertDescription>
        </Alert>
      )}
      {view.missing.map((kind) => {
        const fallback = models.find((model) => model.kind === kind && model.default)
        return (
          <Alert key={kind}>
            <TriangleAlert className="text-warning" />
            <AlertDescription>
              {`Your saved ${KIND_NAMES[kind]} is not installed: ${fallback?.label ?? 'the default'} is used meanwhile.`}
            </AlertDescription>
          </Alert>
        )
      })}

      <section className="flex flex-col gap-2">
        <h3 className="text-sm font-medium">Speech recognition</h3>
        <ModelList
          label="Speech recognition model"
          kind="recognition"
          models={models}
          manageable={catalogue.data.recognition_manageable}
          pending={view.pending}
          onUse={(model) => void chooseModel(model)}
        />
      </section>

      <TurnLength
        maxTurnS={view.max_turn_s}
        model={models.find((model) => model.kind === 'recognition' && model.selected)}
        disabled={save.isPending}
        onChange={(seconds) => {
          update({ max_turn_s: seconds })
        }}
      />

      <section className="flex flex-col gap-2">
        <h3 className="text-sm font-medium">Tutor&apos;s voice</h3>
        <ModelList
          label="Voice model"
          kind="voice"
          models={models}
          manageable={catalogue.data.voice_manageable}
          pending={view.pending}
          onUse={(model) => void chooseModel(model)}
        />
        <VoicePicker
          model={view.tts_model}
          voices={voices.data}
          voice={view.tts_voice}
          speed={view.tts_speed}
          disabled={save.isPending}
          onVoice={(voice) => {
            update({ tts_voice: voice })
          }}
          onSpeed={(speed) => {
            update({ tts_speed: speed })
          }}
        />
      </section>

      <div className="text-muted-foreground flex flex-col gap-1 text-xs">
        <p>Changes apply from your next conversation.</p>
        <p role="status" className="flex min-h-5 items-center gap-1.5">
          {save.isPending && (
            <>
              <Loader2 className="size-3 animate-spin" aria-hidden="true" /> Saving…
            </>
          )}
          {save.isSuccess && (
            <>
              <Check className="text-success size-3" aria-hidden="true" /> Saved
            </>
          )}
          {save.isError && <span className="text-destructive">{errorMessage(save.error)}</span>}
        </p>
      </div>
    </div>
  )
}

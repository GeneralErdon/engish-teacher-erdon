import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Loader2, TriangleAlert } from 'lucide-react'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Skeleton } from '@/components/ui/skeleton'
import type { Schemas } from '@/lib/api/client'
import { errorMessage } from '@/lib/api/errors'

import { EngineChoice } from './engine-choice'
import { ModelList } from './speech-models'
import { TurnLength } from './turn-length'
import {
  speechSettingsQuery,
  useSaveSpeechSettings,
  useSpeechModels,
  voicesQuery,
} from './use-speech'
import { VoicePicker } from './voice-picker'

type Engine = Schemas['SttEngine']
type Model = Schemas['SpeechModel']
type Settings = Schemas['SpeechSettings']
type View = Schemas['SpeechSettingsView']

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
  const { models, engines, last_error: lastError } = catalogue.data
  const running = (engine: Engine) => engines.find((state) => state.engine === engine)?.running
  // The saved engine, unless it is down: the api then transcribes with Speaches.
  const engineInUse: Engine = running(view.stt_engine) ? view.stt_engine : 'openai'
  const gpuDown = view.stt_engine === 'whispercpp' && engineInUse === 'openai'
  /** The settings as cached when a change is sent, not as rendered: a save may have landed since. */
  const latest = (): Settings => {
    const cached = queryClient.getQueryData<View>(speechSettingsQuery.queryKey) ?? view
    return {
      stt_model: cached.stt_model,
      stt_engine: cached.stt_engine,
      stt_gpu_model: cached.stt_gpu_model,
      tts_model: cached.tts_model,
      tts_voice: cached.tts_voice,
      tts_speed: cached.tts_speed,
      max_turn_s: cached.max_turn_s,
    }
  }
  const update = (change: Partial<Settings>) => {
    save.mutate({ body: { ...latest(), ...change } })
  }

  const chooseModel = async (model: Model) => {
    if (model.kind === 'recognition') {
      // Each engine keeps its own model: choosing one never touches the other's.
      update(
        model.engine === 'whispercpp'
          ? { stt_gpu_model: model.model_id }
          : { stt_model: model.model_id },
      )
      return
    }
    // Keep the voice if the new model has it, else its first: the api re-validates anyway.
    const ids = await queryClient
      .query(voicesQuery(model.model_id))
      .then((list) => list.map((voice) => voice.id))
      .catch((): string[] => [])
    const voice = latest().tts_voice
    update({
      tts_model: model.model_id,
      tts_voice: ids.includes(voice) ? voice : (ids[0] ?? voice),
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
      {gpuDown && (
        <Alert>
          <TriangleAlert className="text-warning" />
          <AlertDescription>
            whisper.cpp (GPU) is not running: Speaches is used meanwhile.
          </AlertDescription>
        </Alert>
      )}
      {view.missing.map((kind) => {
        const fallback = models.find(
          (model) =>
            model.kind === kind &&
            model.default &&
            (kind === 'voice' || model.engine === engineInUse),
        )
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
        <EngineChoice
          engines={engines}
          value={view.stt_engine}
          disabled={save.isPending}
          onChange={(engine) => {
            update({ stt_engine: engine })
          }}
        />
        <ModelList
          label="Speech recognition model"
          kind="recognition"
          engine={view.stt_engine}
          models={models}
          manageable={
            view.stt_engine === 'whispercpp'
              ? (engines.find((state) => state.engine === 'whispercpp')?.manageable ?? false)
              : catalogue.data.recognition_manageable
          }
          pending={view.pending}
          disabled={save.isPending}
          onUse={(model) => void chooseModel(model)}
        />
      </section>

      <TurnLength
        maxTurnS={view.max_turn_s}
        model={models.find(
          (model) => model.kind === 'recognition' && model.engine === engineInUse && model.selected,
        )}
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
          disabled={save.isPending}
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

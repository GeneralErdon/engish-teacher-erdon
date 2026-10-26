import { SegmentedControl } from '@/components/segmented-control'
import type { Schemas } from '@/lib/api/client'

const TURNS = [
  { value: '30', label: '30 s' },
  { value: '60', label: '1 min' },
  { value: '120', label: '2 min' },
  { value: '180', label: '3 min' },
  { value: '300', label: '5 min' },
] as const

/** Longest turn, with what it costs: transcription starts only when the turn ends. */
export function TurnLength({
  maxTurnS,
  model,
  disabled,
  onChange,
}: {
  maxTurnS: number
  /** The recognition model in use, for the measured speed. */
  model: Schemas['SpeechModel'] | undefined
  disabled: boolean
  onChange: (seconds: number) => void
}) {
  const length =
    TURNS.find((turn) => Number(turn.value) === maxTurnS)?.label ?? `${String(maxTurnS)} s`
  const estimate =
    model && model.ms_per_audio_s !== null
      ? {
          label: model.label,
          seconds: Math.round((maxTurnS * model.ms_per_audio_s) / 1000),
        }
      : null

  return (
    <div className="flex flex-col gap-2">
      <span className="text-sm font-medium">Longest turn</span>
      <SegmentedControl
        label="Longest turn"
        options={TURNS}
        value={String(maxTurnS) as (typeof TURNS)[number]['value']}
        disabled={disabled}
        onChange={(value) => {
          onChange(Number(value))
        }}
      />
      <p className="text-muted-foreground text-xs">
        {estimate === null
          ? 'Talk a few voice turns and an estimate of the transcription time appears here.'
          : `With ${estimate.label}, ${length} of speech take about ${String(estimate.seconds)} s to transcribe here.`}
        {maxTurnS > 60 && ' The tutor starts answering only after the whole turn is transcribed.'}
      </p>
    </div>
  )
}

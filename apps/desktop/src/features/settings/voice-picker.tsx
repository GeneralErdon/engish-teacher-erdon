import { Loader2, Play, Square } from 'lucide-react'
import { RadioGroup as RadioGroupPrimitive } from 'radix-ui'
import type { ReactNode } from 'react'

import { SegmentedControl } from '@/components/segmented-control'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import type { Schemas } from '@/lib/api/client'
import { cn } from '@/lib/utils'

import { usePreview } from './use-preview'

type Voice = Schemas['Voice']

const SPEEDS = [0.7, 0.8, 0.9, 0.95, 1, 1.1, 1.2, 1.3].map((speed) => ({
  value: String(speed),
  label: `${String(speed)}×`,
}))

const ACCENTS: [Voice['accent'], string][] = [
  ['american', 'American'],
  ['british', 'British'],
  [null, 'Other'],
]
const GENDERS: [Voice['gender'], string][] = [
  ['female', 'Female'],
  ['male', 'Male'],
  [null, 'Other'],
]

/**
 * The voices of the voice model, grouped by accent and gender, each with a preview (one plays at
 * a time; its button stops it); and speed.
 */
export function VoicePicker({
  model,
  voices,
  voicesError,
  voice,
  speed,
  disabled,
  onVoice,
  onSpeed,
}: {
  model: string
  /** Undefined while loading. */
  voices: readonly Voice[] | undefined
  /** Shown instead of the voices when they could not be loaded. */
  voicesError?: ReactNode
  voice: string
  speed: number
  disabled: boolean
  onVoice: (voice: string) => void
  onSpeed: (speed: number) => void
}) {
  const preview = usePreview()

  return (
    <div className="flex flex-col gap-4">
      {voices === undefined && voicesError ? (
        voicesError
      ) : voices === undefined ? (
        <Skeleton aria-label="Loading voices" className="h-20 rounded-xl" />
      ) : voices.length === 0 ? (
        <p className="text-muted-foreground text-xs">This voice model does not list its voices.</p>
      ) : (
        <RadioGroupPrimitive.Root
          aria-label="Voice"
          value={voice}
          disabled={disabled}
          onValueChange={onVoice}
          className="flex flex-col gap-3"
        >
          {ACCENTS.map(([accent, accentLabel]) => {
            const ofAccent = voices.filter((v) => v.accent === accent)
            if (ofAccent.length === 0) return null
            return (
              <section key={accentLabel} aria-label={accentLabel} className="flex flex-col gap-2">
                <h4 className="text-sm font-medium">{accentLabel}</h4>
                {GENDERS.map(([gender, genderLabel]) => {
                  const group = ofAccent.filter((v) => v.gender === gender)
                  if (group.length === 0) return null
                  return (
                    <div
                      key={genderLabel}
                      role="group"
                      aria-label={`${accentLabel} ${genderLabel}`}
                      className="flex flex-wrap items-center gap-2"
                    >
                      <span className="text-muted-foreground w-14 text-xs">{genderLabel}</span>
                      {group.map((v) => {
                        const previewing =
                          preview.current?.voice === v.id ? preview.current : undefined
                        return (
                          <span
                            key={v.id}
                            className={cn(
                              'flex items-center rounded-lg border',
                              v.id === voice && 'border-primary',
                            )}
                          >
                            <RadioGroupPrimitive.Item
                              value={v.id}
                              className="focus-visible:ring-ring/50 data-[state=checked]:font-medium rounded-l-lg px-3 py-1.5 text-sm outline-none focus-visible:ring-[3px] disabled:opacity-60"
                            >
                              {v.name}
                            </RadioGroupPrimitive.Item>
                            <Button
                              size="icon-xs"
                              variant="ghost"
                              aria-label={
                                previewing ? `Stop preview of ${v.name}` : `Preview ${v.name}`
                              }
                              onClick={() => {
                                preview.toggle({ model, voice: v.id, speed })
                              }}
                            >
                              {!previewing ? (
                                <Play />
                              ) : previewing.playing ? (
                                <Square className="fill-current" />
                              ) : (
                                <Loader2 className="animate-spin" />
                              )}
                            </Button>
                          </span>
                        )
                      })}
                    </div>
                  )
                })}
              </section>
            )
          })}
        </RadioGroupPrimitive.Root>
      )}
      {preview.error && (
        <p role="alert" className="text-destructive text-xs">
          {preview.error}
        </p>
      )}
      <div className="flex flex-col gap-2">
        <span className="text-sm font-medium">Speed</span>
        <SegmentedControl
          label="Speed"
          options={SPEEDS}
          value={String(speed)}
          disabled={disabled}
          onChange={(value) => {
            onSpeed(Number(value))
          }}
        />
      </div>
    </div>
  )
}

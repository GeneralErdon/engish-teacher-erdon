import { RadioGroup as RadioGroupPrimitive } from 'radix-ui'

import type { Schemas } from '@/lib/api/client'
import { cn } from '@/lib/utils'

type Engine = Schemas['SttEngine']

const OPTIONS: readonly { engine: Engine; label: string; hint: (running: boolean) => string }[] = [
  {
    engine: 'openai',
    label: 'Speaches · CPU',
    hint: () => 'Uses an NVIDIA GPU with the `nvidia` profile',
  },
  {
    engine: 'whispercpp',
    label: 'whisper.cpp · GPU',
    hint: (running) =>
      running
        ? 'AMD and Intel GPUs, through Vulkan'
        : 'Start it with `just voice gpu` (Linux, AMD or Intel GPU)',
  },
]

/** Which engine transcribes: a two-segment control. A stopped engine cannot be picked. */
export function EngineChoice({
  engines,
  value,
  disabled = false,
  onChange,
}: {
  engines: readonly Schemas['SpeechEngineState'][]
  value: Engine
  /** Nothing can be chosen meanwhile (a settings save is running). */
  disabled?: boolean
  onChange: (engine: Engine) => void
}) {
  return (
    <RadioGroupPrimitive.Root
      aria-label="Speech recognition engine"
      value={value}
      disabled={disabled}
      onValueChange={(next) => {
        onChange(next as Engine)
      }}
      className="grid gap-2 sm:grid-cols-2"
    >
      {OPTIONS.map(({ engine, label, hint }) => {
        const running = engines.find((state) => state.engine === engine)?.running ?? false
        const titleId = `engine-${engine}`
        return (
          <RadioGroupPrimitive.Item
            key={engine}
            value={engine}
            disabled={!running}
            aria-labelledby={titleId}
            aria-describedby={`${titleId}-hint`}
            className={cn(
              'focus-visible:ring-ring/50 flex flex-col gap-1 rounded-lg border p-3 text-left text-sm outline-none focus-visible:ring-[3px] disabled:opacity-60',
              'data-[state=checked]:border-primary',
            )}
          >
            <span id={titleId} className="font-medium">
              {label}
            </span>
            <span id={`${titleId}-hint`} className="text-muted-foreground text-xs">
              {hint(running)}
            </span>
          </RadioGroupPrimitive.Item>
        )
      })}
    </RadioGroupPrimitive.Root>
  )
}

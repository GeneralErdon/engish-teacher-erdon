import {
  Cloud,
  Feather,
  Gem,
  HardDrive,
  KeyRound,
  Plug,
  Server,
  Sparkles,
  type LucideIcon,
} from 'lucide-react'
import { RadioGroup as RadioGroupPrimitive } from 'radix-ui'

import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

import type { LlmSettings, ProviderInfo, ProviderKind } from './use-llm'

const ICONS: Record<ProviderKind, LucideIcon> = {
  ollama: HardDrive,
  ollama_cloud: Cloud,
  openai: Sparkles,
  anthropic: Feather,
  gemini: Gem,
  openai_compatible: Server,
  anthropic_compatible: Plug,
}

/** The providers as selectable cards (a radio group: arrow keys move between them). */
export function ProviderPicker({
  providers,
  settings,
  value,
  onChange,
}: {
  providers: readonly ProviderInfo[]
  settings: LlmSettings
  value: ProviderKind
  onChange: (kind: ProviderKind) => void
}) {
  const saved = new Set(settings.providers.map((p) => p.kind))

  return (
    <RadioGroupPrimitive.Root
      aria-label="Provider"
      value={value}
      onValueChange={(kind) => {
        onChange(kind as ProviderKind)
      }}
      className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3"
    >
      {providers.map((provider) => {
        const Icon = ICONS[provider.kind]
        return (
          <RadioGroupPrimitive.Item
            key={provider.kind}
            value={provider.kind}
            className={cn(
              'group bg-card relative flex flex-col items-start gap-2 rounded-xl border p-4 text-left transition-[border-color,box-shadow,transform] outline-none',
              'hover:border-primary/40 focus-visible:ring-ring/50 focus-visible:ring-[3px] motion-safe:active:scale-[0.98]',
              'data-[state=checked]:border-primary data-[state=checked]:shadow-[0_0_0_1px] data-[state=checked]:shadow-primary/60',
            )}
          >
            <span className="flex w-full items-center gap-2">
              <span className="bg-secondary text-primary group-data-[state=checked]:bg-primary group-data-[state=checked]:text-primary-foreground grid size-8 place-items-center rounded-lg transition-colors">
                <Icon className="size-4" aria-hidden="true" />
              </span>
              <span className="font-medium">{provider.label}</span>
              {settings.active === provider.kind && (
                <Badge className="bg-success/15 text-success ml-auto">Active</Badge>
              )}
              {settings.active !== provider.kind && saved.has(provider.kind) && (
                <Badge variant="secondary" className="ml-auto">
                  Saved
                </Badge>
              )}
            </span>
            <span className="text-muted-foreground text-xs leading-relaxed">
              {provider.description}
            </span>
            {provider.api_key === 'required' && (
              <span className="text-muted-foreground mt-auto inline-flex items-center gap-1 text-[11px]">
                <KeyRound className="size-3" aria-hidden="true" /> API key
              </span>
            )}
          </RadioGroupPrimitive.Item>
        )
      })}
    </RadioGroupPrimitive.Root>
  )
}

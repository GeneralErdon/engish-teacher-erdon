import { Loader2, RefreshCw } from 'lucide-react'
import { AnimatePresence, m } from 'motion/react'
import type { UseFormRegisterReturn } from 'react-hook-form'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

import { Field } from './field'

const MAX_SHOWN = 60

function hintFor(models: string[] | undefined, visible: number, loadError: string | undefined) {
  if (loadError) return loadError
  if (!models) return 'Type a model name, or load the list from the provider.'
  if (visible === 0) return 'No listed model matches: the name will be used as typed.'
  return `${String(models.length)} models available.`
}

/**
 * A free-text model field plus the provider's own list, filtered by what is typed. Free text
 * stays possible: some servers do not list their models.
 */
export function ModelPicker({
  register,
  error,
  models,
  loading,
  loadError,
  onLoad,
  onPick,
  current,
  disabled,
}: {
  register: UseFormRegisterReturn
  error: string | undefined
  models: string[] | undefined
  loading: boolean
  loadError: string | undefined
  onLoad: () => void
  onPick: (id: string) => void
  current: string
  disabled: boolean
}) {
  const query = current.trim().toLowerCase()
  const all = models ?? []
  // Once a listed model is picked, keep showing the alternatives.
  const visible = all.includes(current) ? all : all.filter((id) => id.toLowerCase().includes(query))

  return (
    <div className="flex flex-col gap-3">
      <Field
        label="Model"
        action={
          <Button type="button" variant="secondary" size="sm" disabled={disabled} onClick={onLoad}>
            {loading ? <Loader2 className="animate-spin" /> : <RefreshCw />}
            Load models
          </Button>
        }
        hint={hintFor(models, visible.length, loadError)}
        error={error}
      >
        {(control) => (
          <Input
            autoComplete="off"
            spellCheck={false}
            placeholder="e.g. gpt-oss:120b"
            {...control}
            {...register}
          />
        )}
      </Field>

      <AnimatePresence>
        {visible.length > 0 && (
          <m.ul
            aria-label="Available models"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="flex max-h-44 flex-wrap gap-2 overflow-y-auto p-0.5"
          >
            {visible.slice(0, MAX_SHOWN).map((id) => (
              <li key={id}>
                <button
                  type="button"
                  aria-pressed={id === current}
                  onClick={() => {
                    onPick(id)
                  }}
                  className={cn(
                    'hover:border-primary/50 focus-visible:ring-ring/50 rounded-full border px-3 py-1 font-mono text-xs transition-colors outline-none focus-visible:ring-[3px]',
                    id === current && 'border-primary bg-primary text-primary-foreground',
                  )}
                >
                  {id}
                </button>
              </li>
            ))}
          </m.ul>
        )}
      </AnimatePresence>
    </div>
  )
}

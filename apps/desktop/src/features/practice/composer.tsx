import { ArrowUp, Loader2, Mic, Square } from 'lucide-react'
import { useState, type KeyboardEvent } from 'react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

import { clock, useElapsedSeconds } from './use-elapsed'
import type { RecorderState } from './use-recorder'

/**
 * Type and press Enter (Shift+Enter for a new line), or press the microphone, speak, and press
 * it again to send. While the tutor answers (writing or speaking), a stop button interrupts it.
 */
export function Composer({
  disabled,
  replying,
  recorder,
  meter,
  onSend,
  onStop,
  onMic,
}: {
  disabled: boolean
  replying: boolean
  recorder: RecorderState
  /** Microphone level, 0..1. */
  meter: number
  onSend: (text: string) => void
  onStop: () => void
  onMic: () => void
}) {
  const [text, setText] = useState('')
  const message = text.trim()
  const recording = recorder === 'recording'

  const send = () => {
    if (!message || disabled) return
    onSend(message)
    setText('')
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      send()
    }
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        send()
      }}
      className={cn(
        'bg-card focus-within:ring-ring/50 flex items-end gap-2 rounded-2xl border p-2 shadow-sm transition-colors focus-within:ring-[3px]',
        recording && 'border-destructive/60',
      )}
    >
      {recording ? (
        <Listening meter={meter} />
      ) : (
        <textarea
          aria-label="Message"
          rows={1}
          value={text}
          disabled={disabled}
          placeholder={disabled ? 'Connecting…' : 'Write in English, or press the mic and speak'}
          onChange={(event) => {
            setText(event.target.value)
          }}
          onKeyDown={onKeyDown}
          className="placeholder:text-muted-foreground field-sizing-content max-h-40 min-h-9 flex-1 resize-none bg-transparent px-2 py-1.5 text-sm outline-none disabled:opacity-60"
        />
      )}

      <Button
        type="button"
        size="icon"
        variant={recording ? 'destructive' : 'secondary'}
        aria-label={recording ? 'Stop and send' : 'Speak'}
        aria-pressed={recording}
        disabled={disabled || recorder === 'starting'}
        onClick={onMic}
      >
        {recorder === 'starting' ? (
          <Loader2 className="animate-spin" />
        ) : recording ? (
          <Square className="fill-current" />
        ) : (
          <Mic />
        )}
      </Button>

      {!recording &&
        (replying ? (
          <Button type="button" size="icon" variant="secondary" aria-label="Stop" onClick={onStop}>
            <Square className="fill-current" />
          </Button>
        ) : (
          <Button type="submit" size="icon" aria-label="Send" disabled={disabled || !message}>
            <ArrowUp />
          </Button>
        ))}
    </form>
  )
}

/** "Listening… 0:04" with a live level meter. */
function Listening({ meter }: { meter: number }) {
  const seconds = useElapsedSeconds()

  return (
    <div role="status" className="flex min-h-9 flex-1 items-center gap-3 px-2 text-sm">
      <span
        aria-hidden="true"
        className="bg-destructive size-2.5 rounded-full motion-safe:animate-pulse"
      />
      <span>Listening… {clock(seconds)}</span>
      <span aria-hidden="true" className="bg-muted h-1.5 flex-1 overflow-hidden rounded-full">
        <span
          className="bg-destructive block h-full origin-left rounded-full transition-transform duration-100"
          style={{ transform: `scaleX(${String(Math.min(1, meter * 4))})` }}
        />
      </span>
    </div>
  )
}

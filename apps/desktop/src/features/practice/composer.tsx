import { ArrowUp, Square } from 'lucide-react'
import { useState, type KeyboardEvent } from 'react'

import { Button } from '@/components/ui/button'

/** Enter sends, Shift+Enter adds a line. While the tutor answers, a stop button interrupts. */
export function Composer({
  disabled,
  replying,
  onSend,
  onStop,
}: {
  disabled: boolean
  replying: boolean
  onSend: (text: string) => void
  onStop: () => void
}) {
  const [text, setText] = useState('')
  const message = text.trim()

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
      className="bg-card focus-within:ring-ring/50 flex items-end gap-2 rounded-2xl border p-2 shadow-sm focus-within:ring-[3px]"
    >
      <textarea
        aria-label="Message"
        rows={1}
        value={text}
        disabled={disabled}
        placeholder={disabled ? 'Connecting…' : 'Write in English… (Enter to send)'}
        onChange={(event) => {
          setText(event.target.value)
        }}
        onKeyDown={onKeyDown}
        className="placeholder:text-muted-foreground field-sizing-content max-h-40 min-h-9 flex-1 resize-none bg-transparent px-2 py-1.5 text-sm outline-none disabled:opacity-60"
      />
      {replying ? (
        <Button type="button" size="icon" variant="secondary" aria-label="Stop" onClick={onStop}>
          <Square className="fill-current" />
        </Button>
      ) : (
        <Button type="submit" size="icon" aria-label="Send" disabled={disabled || !message}>
          <ArrowUp />
        </Button>
      )}
    </form>
  )
}

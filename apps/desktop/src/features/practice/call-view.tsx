import { Captions, CaptionsOff, Mic, MicOff, PhoneOff } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

import { Orb } from './orb'
import { useCall, type CallPhase } from './use-call'
import type { Conversation } from './use-conversation'
import { clock, useElapsedSeconds } from './use-elapsed'

const STATUS: Record<CallPhase, string> = {
  starting: 'Connecting…',
  listening: 'Go ahead, I’m listening',
  hearing: 'Listening…',
  thinking: 'Thinking…',
  speaking: 'Speaking · talk to interrupt',
}

/**
 * A voice call with the tutor: no buttons between turns. The orb follows whoever is talking;
 * captions show the last exchange, and corrections wait in the chat until the call ends.
 */
export function CallView({
  conversation,
  onEnd,
}: {
  conversation: Conversation
  onEnd: () => void
}) {
  const call = useCall(conversation)
  const [captions, setCaptions] = useState(true)
  const seconds = useElapsedSeconds()
  const endButton = useRef<HTMLButtonElement>(null)
  // Turns from before the call are not this call's corrections.
  const [firstTurn] = useState(conversation.turns.length)
  const corrections = conversation.turns
    .slice(firstTurn)
    .reduce((count, turn) => count + (turn.correction?.items.length ?? 0), 0)
  const last = conversation.turns.at(-1)
  const level = call.phase === 'speaking' ? conversation.outputLevel : call.micLevel

  useEffect(() => {
    endButton.current?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onEnd()
    }
    window.addEventListener('keydown', onKey)
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = overflow
    }
  }, [onEnd])

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Call with your tutor"
      className="bg-background fixed inset-0 z-50 flex flex-col items-center gap-6 bg-[radial-gradient(38rem_30rem_at_50%_35%,var(--glow-1),transparent_70%)] px-6 pt-[max(1.5rem,env(safe-area-inset-top))] pb-[max(2rem,env(safe-area-inset-bottom))]"
    >
      <header className="text-muted-foreground flex w-full max-w-md items-center justify-between font-mono text-sm">
        <span className="flex items-center gap-2">
          <span
            aria-hidden="true"
            className="bg-success size-2 rounded-full motion-safe:animate-pulse"
          />
          <span>
            Call <span aria-label="Duration">{clock(seconds)}</span>
          </span>
        </span>
        {conversation.session && (
          <Badge variant="secondary">Level {conversation.session.level}</Badge>
        )}
      </header>

      <div className="flex w-full flex-1 flex-col items-center justify-center gap-8">
        <Orb phase={call.phase} level={level} className="w-[min(64vw,18rem)]" />
        <div className="flex min-h-14 flex-col items-center gap-1 text-center">
          <p role="status" className="text-lg font-medium">
            {call.error
              ? 'The microphone did not start'
              : call.muted
                ? 'Muted'
                : STATUS[call.phase]}
          </p>
          {(call.error ?? conversation.error) && (
            <p className="text-destructive text-sm">{call.error ?? conversation.error}</p>
          )}
          {conversation.notice && (
            <p className="text-muted-foreground text-sm">{conversation.notice}</p>
          )}
        </div>
      </div>

      <div className="flex max-h-[30dvh] min-h-20 w-full max-w-md flex-col justify-end gap-2 overflow-y-auto text-center">
        {captions && last && (
          <div aria-label="Live captions" className="flex flex-col gap-2">
            <p className="text-muted-foreground text-sm">
              <Mic className="mr-1 inline size-3.5" aria-label="You" />
              {last.text}
            </p>
            <p className="text-base leading-relaxed">{last.reply}</p>
          </div>
        )}
        {corrections > 0 && (
          <p className="text-muted-foreground text-xs">
            {corrections} {corrections === 1 ? 'correction' : 'corrections'} to review after the
            call
          </p>
        )}
      </div>

      <footer className="flex items-center gap-5">
        <Button
          size="icon-lg"
          variant="secondary"
          className="size-14 rounded-full [&_svg]:size-6!"
          aria-label={call.muted ? 'Unmute' : 'Mute'}
          aria-pressed={call.muted}
          disabled={call.phase === 'starting'}
          onClick={() => void call.toggleMute()}
        >
          {call.muted ? <MicOff /> : <Mic />}
        </Button>
        {/* Solid red in both themes: the white icon stays above 4.5:1 (the dark token is lighter). */}
        <Button
          ref={endButton}
          size="icon-lg"
          variant="destructive"
          className="dark:bg-[oklch(0.58_0.2_22)] size-16 rounded-full shadow-lg shadow-destructive/30 [&_svg]:size-7!"
          aria-label="End call"
          onClick={onEnd}
        >
          <PhoneOff />
        </Button>
        <Button
          size="icon-lg"
          variant="secondary"
          className={cn('size-14 rounded-full [&_svg]:size-6!', !captions && 'opacity-70')}
          aria-label="Captions"
          aria-pressed={captions}
          onClick={() => {
            setCaptions(!captions)
          }}
        >
          {captions ? <Captions /> : <CaptionsOff />}
        </Button>
      </footer>
    </div>,
    document.body,
  )
}

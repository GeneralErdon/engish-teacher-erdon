import { Link } from '@tanstack/react-router'
import { MessagesSquare, RotateCw, WifiOff } from 'lucide-react'
import { useEffect, useRef } from 'react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'

import { Composer } from './composer'
import { TurnView } from './turn-view'
import { useConversation } from './use-conversation'

const STARTERS = [
  'Hi! Can we talk about my weekend?',
  "I'd like to practise ordering food in a restaurant.",
  'Can you help me prepare for a job interview?',
]

export function PracticePage() {
  const conversation = useConversation()
  const end = useRef<HTMLDivElement>(null)
  const { turns, session, status } = conversation
  const lastReply = turns.at(-1)?.reply

  // Follow the conversation as it grows, including while a reply streams in.
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' })
  }, [turns.length, lastReply])

  return (
    <div className="flex min-h-[calc(100dvh-12rem)] flex-col gap-4">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-3xl font-semibold">Practice</h1>
        {session && (
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="secondary">Level {session.level}</Badge>
            <Badge variant="outline">
              {session.provider} · {session.model}
            </Badge>
          </div>
        )}
      </header>

      {status === 'closed' && (
        <Alert variant="destructive">
          <WifiOff />
          <AlertTitle>Disconnected from the tutor</AlertTitle>
          <AlertDescription className="flex flex-col items-start gap-3">
            Is the backend running? Start it with <code>just dev-api</code>.
            <Button size="sm" variant="outline" onClick={conversation.reconnect}>
              <RotateCw /> Reconnect
            </Button>
          </AlertDescription>
        </Alert>
      )}
      {conversation.error && (
        <Alert variant="destructive">
          <AlertTitle>{conversation.error}</AlertTitle>
        </Alert>
      )}

      {turns.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-5 py-10 text-center">
          <span className="from-primary to-highlight text-primary-foreground grid size-14 place-items-center rounded-2xl bg-linear-to-br shadow-lg shadow-primary/25">
            <MessagesSquare className="size-7" aria-hidden="true" />
          </span>
          <div className="flex max-w-md flex-col gap-1.5">
            <h2 className="text-xl font-semibold">Say anything, in English</h2>
            <p className="text-muted-foreground text-sm">
              Your tutor answers and keeps the conversation going. Mistakes are marked under your
              message, explained in the language you chose in{' '}
              <Link to="/settings" className="text-primary underline-offset-4 hover:underline">
                Settings
              </Link>
              .
            </p>
          </div>
          <div className="flex flex-wrap justify-center gap-2">
            {STARTERS.map((starter) => (
              <Button
                key={starter}
                variant="outline"
                size="sm"
                disabled={!session}
                onClick={() => {
                  conversation.say(starter)
                }}
              >
                {starter}
              </Button>
            ))}
          </div>
        </div>
      ) : (
        <ol aria-label="Conversation" aria-live="polite" className="flex flex-1 flex-col gap-6">
          {turns.map((turn) => (
            <TurnView key={turn.id} turn={turn} />
          ))}
        </ol>
      )}
      <div ref={end} />

      <div className="sticky bottom-24 md:bottom-6">
        <Composer
          disabled={!session || status !== 'open'}
          replying={conversation.replying}
          onSend={conversation.say}
          onStop={conversation.interrupt}
        />
      </div>
    </div>
  )
}

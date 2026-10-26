import { Mic, Volume2 } from 'lucide-react'
import { Link } from '@tanstack/react-router'
import { m } from 'motion/react'

import { Badge } from '@/components/ui/badge'

import { CorrectionView } from './correction-view'
import type { Turn } from './use-conversation'

const seconds = (ms: number) => `${(ms / 1000).toFixed(1)} s`

const appear = { initial: { opacity: 0, y: 8 }, animate: { opacity: 1, y: 0 } }

/** One exchange: the learner's message with its correction, then the tutor's reply. */
export function TurnView({ turn, speaking = false }: { turn: Turn; speaking?: boolean }) {
  return (
    <li className="flex flex-col gap-3">
      <m.div {...appear} className="flex flex-col items-end gap-2 self-end sm:max-w-[80%]">
        <div className="bg-primary text-primary-foreground rounded-2xl rounded-br-md px-4 py-2.5 shadow-sm">
          {turn.source === 'voice' && (
            <Mic className="mr-1.5 inline size-3.5 opacity-80" aria-label="Spoken" />
          )}
          {turn.text}
        </div>
        {turn.cut && (
          <p className="text-muted-foreground px-1 font-mono text-[11px]">
            <span>Cut at the turn limit</span> ·{' '}
            <Link to="/settings" className="underline underline-offset-4">
              Allow longer turns
            </Link>
          </p>
        )}
        <CorrectionView text={turn.text} correction={turn.correction} />
      </m.div>

      <m.div {...appear} className="flex flex-col items-start gap-1 self-start sm:max-w-[80%]">
        <div className="bg-card rounded-2xl rounded-bl-md border px-4 py-2.5 shadow-sm">
          {turn.error ? (
            <span className="text-destructive">{turn.error}</span>
          ) : (
            <>
              {turn.reply}
              {!turn.replyDone && (
                <span
                  aria-hidden="true"
                  className="bg-primary ml-0.5 inline-block h-4 w-1.5 translate-y-0.5 rounded-sm motion-safe:animate-pulse"
                />
              )}
            </>
          )}
        </div>
        <div className="text-muted-foreground flex items-center gap-2 px-1 font-mono text-[11px]">
          {speaking && (
            <Volume2
              role="img"
              aria-label="Speaking"
              className="text-primary size-3.5 motion-safe:animate-pulse"
            />
          )}
          {turn.interrupted && <Badge variant="outline">Interrupted</Badge>}
          {turn.metrics && (
            <span title="Latency: speech recognition, then until the tutor's first word, first sound and whole reply. Voice to voice = heard + first sound">
              {turn.sttMs !== null && `heard ${seconds(turn.sttMs)} · `}
              {turn.metrics.first_token_ms !== null &&
                `first word ${seconds(turn.metrics.first_token_ms)} · `}
              {turn.metrics.first_audio_ms !== null &&
                `first sound ${seconds(turn.metrics.first_audio_ms)} · `}
              reply {seconds(turn.metrics.reply_ms)}
            </span>
          )}
        </div>
      </m.div>
    </li>
  )
}

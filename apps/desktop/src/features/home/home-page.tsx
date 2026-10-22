import { Link } from '@tanstack/react-router'
import {
  ArrowRight,
  Bot,
  Check,
  MessagesSquare,
  Mic,
  RotateCw,
  Server,
  ShieldCheck,
} from 'lucide-react'
import { m, type Variants } from 'motion/react'
import type { ReactNode } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useLlmSettings, useProviders } from '@/features/settings/use-llm'
import { useSpeechStatus } from '@/features/settings/use-speech'
import { useHealth } from '@/features/status/use-health'
import { backendUrl } from '@/lib/platform'
import { cn } from '@/lib/utils'

import { VoiceWave } from './voice-wave'

const list: Variants = { show: { transition: { staggerChildren: 0.07 } } }
const item: Variants = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.4, ease: [0.22, 1, 0.36, 1] } },
}

export function HomePage() {
  const health = useHealth()
  const online = health.isSuccess
  const settings = useLlmSettings({ enabled: online })
  const providers = useProviders({ enabled: online })
  const speech = useSpeechStatus({ enabled: online })
  const active = settings.data?.active
  const provider = providers.data?.find((p) => p.kind === active)
  const model = settings.data?.providers.find((p) => p.kind === active)?.model
  const modelChosen = settings.data?.source === 'saved'

  return (
    <m.div variants={list} initial="hidden" animate="show" className="flex flex-col gap-8">
      <m.section variants={item} aria-labelledby="welcome">
        <Card className="relative gap-0 overflow-hidden p-6 sm:p-10">
          <div className="relative z-10 flex max-w-2xl flex-col items-start gap-5">
            <Badge variant="secondary" className="gap-1.5">
              <ShieldCheck aria-hidden="true" /> Private · runs on your own machine
            </Badge>
            <h1 id="welcome" className="text-4xl leading-[1.05] font-semibold sm:text-5xl">
              <span className="text-gradient">Speak English</span> with confidence.
            </h1>
            <p className="text-muted-foreground max-w-prose text-base sm:text-lg">
              Your personal speaking coach: real conversations, gentle corrections and honest
              pronunciation feedback, at your own pace.
            </p>
            <div className="flex flex-wrap items-center gap-3">
              <Button size="lg" asChild>
                <Link to="/practice">
                  <MessagesSquare aria-hidden="true" /> Start a conversation
                </Link>
              </Button>
              <Button size="lg" variant="outline" asChild>
                <Link to="/settings">
                  Choose a language model <ArrowRight aria-hidden="true" />
                </Link>
              </Button>
            </div>
          </div>
          <VoiceWave className="absolute -right-6 -bottom-6 h-40 w-72 opacity-60 sm:h-56 sm:w-96" />
        </Card>
      </m.section>

      <m.section variants={item} aria-label="Status" className="grid gap-4 md:grid-cols-3">
        <StatusCard
          icon={<Server />}
          title="Backend"
          badge={
            online ? (
              <Badge className="bg-success/15 text-success">Online</Badge>
            ) : health.isError ? (
              <Badge variant="destructive">Offline</Badge>
            ) : undefined
          }
        >
          {health.isPending && <Skeleton className="h-4 w-32" />}
          {online && (
            <p>
              Version {health.data.version} at <code className="text-xs">{backendUrl()}</code>
            </p>
          )}
          {health.isError && (
            <div className="flex flex-col items-start gap-3">
              <p>
                Start it with <code className="text-xs">just dev-api</code> or{' '}
                <code className="text-xs">just up</code>.
              </p>
              <Button
                size="sm"
                variant="outline"
                onClick={() => void health.refetch()}
                disabled={health.isFetching}
              >
                <RotateCw aria-hidden="true" className={cn(health.isFetching && 'animate-spin')} />
                Retry
              </Button>
            </div>
          )}
        </StatusCard>

        <StatusCard
          icon={<Bot />}
          title="Language model"
          badge={
            settings.data && (
              <Badge variant="secondary">{modelChosen ? 'Saved in the app' : 'From .env'}</Badge>
            )
          }
        >
          {!online && <p>Waiting for the backend.</p>}
          {online && !provider && <Skeleton className="h-4 w-40" />}
          {provider && (
            <div className="flex flex-col items-start gap-2">
              <p>
                <span className="text-foreground font-medium">{provider.label}</span>
                {model && (
                  <>
                    {' · '}
                    <code className="text-xs">{model}</code>
                  </>
                )}
              </p>
              <Button size="sm" variant="link" className="h-auto px-0" asChild>
                <Link to="/settings">Change</Link>
              </Button>
            </div>
          )}
        </StatusCard>

        <StatusCard
          icon={<Mic />}
          title="Voice"
          badge={
            speech.data &&
            (speech.data.model_ready ? (
              <Badge className="bg-success/15 text-success">Ready</Badge>
            ) : (
              <Badge variant="outline">Not set up</Badge>
            ))
          }
        >
          {!online && <p>Waiting for the backend.</p>}
          {online && !speech.data && <Skeleton className="h-4 w-40" />}
          {speech.data && (
            <div className="flex flex-col items-start gap-2">
              <p>
                {speech.data.model_ready
                  ? 'Press the mic in Practice and speak.'
                  : 'Speech recognition runs on your machine; it needs a one-time setup.'}
              </p>
              {!speech.data.model_ready && (
                <Button size="sm" variant="link" className="h-auto px-0" asChild>
                  <Link to="/settings">Set it up</Link>
                </Button>
              )}
            </div>
          )}
        </StatusCard>
      </m.section>

      <m.section variants={item} aria-labelledby="getting-started" className="flex flex-col gap-4">
        <h2 id="getting-started" className="text-xl font-semibold">
          Getting started
        </h2>
        <ol aria-labelledby="getting-started" className="grid gap-3 md:grid-cols-3">
          <Step n={1} done={online} title="Start the backend">
            It runs the tutor on your machine.
          </Step>
          <Step n={2} done={modelChosen} title="Pick a language model">
            Ollama, Ollama Cloud, OpenAI, Anthropic, Gemini or any compatible server.
          </Step>
          <Step n={3} done={false} title="Have your first conversation">
            Write or speak to your tutor in{' '}
            <Link to="/practice" className="text-primary underline-offset-4 hover:underline">
              Practice
            </Link>
            .
          </Step>
        </ol>
      </m.section>
    </m.div>
  )
}

function StatusCard({
  icon,
  title,
  badge,
  children,
}: {
  icon: ReactNode
  title: string
  badge?: ReactNode
  children: ReactNode
}) {
  return (
    <Card className="gap-3 transition-shadow hover:shadow-md">
      <CardHeader className="flex items-center justify-between gap-2">
        <CardTitle className="flex items-center gap-2 text-base [&_svg]:size-4 [&_svg]:text-primary">
          {icon}
          {title}
        </CardTitle>
        {badge}
      </CardHeader>
      <CardContent className="text-muted-foreground text-sm">{children}</CardContent>
    </Card>
  )
}

function Step({
  n,
  done,
  title,
  children,
}: {
  n: number
  done: boolean
  title: string
  children: ReactNode
}) {
  return (
    <li>
      <Card className="h-full gap-2 py-5">
        <CardHeader className="flex items-center gap-3 px-5">
          <span
            className={cn(
              'grid size-7 shrink-0 place-items-center rounded-full border text-xs font-semibold',
              done && 'border-success bg-success text-background',
            )}
          >
            {done ? <Check className="size-4" aria-label="Done" /> : n}
          </span>
          <CardTitle className="text-sm">{title}</CardTitle>
        </CardHeader>
        <CardDescription className="px-5">{children}</CardDescription>
      </Card>
    </li>
  )
}

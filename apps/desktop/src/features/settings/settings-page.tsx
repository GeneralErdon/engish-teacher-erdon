import { AlertTriangle, AudioLines, Bot, GraduationCap, Palette, Server } from 'lucide-react'
import type { ReactNode } from 'react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { BackendStatus } from '@/features/status/backend-status'
import { errorMessage } from '@/lib/api/errors'
import { backendUrl } from '@/lib/platform'

import { AppearanceSection } from './appearance-section'
import { LanguageModelForm } from './language-model-form'
import { LearningSection } from './learning-section'
import { SpeechSection } from './speech-section'
import { useLlmSettings, useProviders } from './use-llm'

export function SettingsPage() {
  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-2">
        <h1 className="text-3xl font-semibold">Settings</h1>
        <p className="text-muted-foreground">
          The model your tutor thinks with, how you learn, and how the app looks.
        </p>
      </header>

      <Section
        icon={<Bot />}
        title="Language model"
        description="Pick who answers: a model on this computer, a free cloud tier, or your own API key. Keys stay in the backend and are never shown again."
      >
        <LanguageModelSection />
      </Section>

      <Section
        icon={<AudioLines />}
        title="Speech recognition"
        description="Turns what you say into text, on your own machine: your voice never leaves it."
      >
        <SpeechSection />
      </Section>

      <Section
        icon={<GraduationCap />}
        title="Learning"
        description="Your level, and the language your mistakes are explained in."
      >
        <LearningSection />
      </Section>

      <Section
        icon={<Palette />}
        title="Appearance"
        description="Follow the system, or pick a theme."
      >
        <AppearanceSection />
      </Section>

      <Section icon={<Server />} title="Backend" description="Where this app finds the tutor.">
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <code className="bg-muted rounded-md px-2 py-1">{backendUrl()}</code>
          <BackendStatus />
        </div>
      </Section>
    </div>
  )
}

function LanguageModelSection() {
  const providers = useProviders()
  const settings = useLlmSettings()

  if (providers.isError || settings.isError) {
    return (
      <Alert variant="destructive">
        <AlertTriangle />
        <AlertTitle>Could not load the model settings</AlertTitle>
        <AlertDescription className="flex flex-col items-start gap-3">
          {errorMessage(providers.isError ? providers.error : settings.error)}
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              void providers.refetch()
              void settings.refetch()
            }}
          >
            Try again
          </Button>
        </AlertDescription>
      </Alert>
    )
  }

  if (!providers.data || !settings.data) {
    return (
      <div aria-label="Loading" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }, (_, index) => (
          <Skeleton key={index} className="h-28 rounded-xl" />
        ))}
      </div>
    )
  }

  return <LanguageModelForm providers={providers.data} settings={settings.data} />
}

function Section({
  icon,
  title,
  description,
  children,
}: {
  icon: ReactNode
  title: string
  description: string
  children: ReactNode
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-lg [&_svg]:size-5 [&_svg]:text-primary">
          {icon}
          <h2>{title}</h2>
        </CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  )
}

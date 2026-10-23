import { zodResolver } from '@hookform/resolvers/zod'
import {
  CheckCircle2,
  ExternalLink,
  Eye,
  EyeOff,
  ListRestart,
  Loader2,
  PlugZap,
  RotateCcw,
  Save,
  XCircle,
} from 'lucide-react'
import { AnimatePresence, m } from 'motion/react'
import { useState } from 'react'
import { useForm, useWatch, type Resolver } from 'react-hook-form'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { api } from '@/lib/api/client'
import { errorMessage } from '@/lib/api/errors'

import { Field } from './field'
import { ModelPicker } from './model-picker'
import { ProviderPicker } from './provider-picker'
import {
  languageModelSchema,
  normalizeUrl,
  type KeyRules,
  type LanguageModelValues,
} from './schema'
import {
  useSetLlmSettings,
  type LlmSettings,
  type ProviderInfo,
  type ProviderKind,
} from './use-llm'

const reveal = {
  initial: { opacity: 0, y: -6 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -6 },
  transition: { duration: 0.2 },
}

/** Rebuilt on every validation from the latest settings (RHF passes `context` to the resolver). */
const resolver: Resolver<LanguageModelValues, KeyRules> = (values, rules, options) =>
  zodResolver(languageModelSchema(rules as KeyRules))(values, rules, options)

function valuesFor(kind: ProviderKind, providers: readonly ProviderInfo[], settings: LlmSettings) {
  const saved = settings.providers.find((p) => p.kind === kind)
  const info = providers.find((p) => p.kind === kind)
  return {
    kind,
    base_url: saved?.base_url ?? info?.default_base_url ?? '',
    api_key: '',
    model: saved?.model ?? info?.suggested_model ?? '',
  }
}

/** `null` asks the api to reuse the saved key (only ever sent to the URL it was saved for). */
function keyToSend(apiKey: string) {
  return apiKey.trim() === '' ? null : apiKey.trim()
}

export function LanguageModelForm({
  providers,
  settings,
}: {
  providers: readonly ProviderInfo[]
  settings: LlmSettings
}) {
  const setSettings = useSetLlmSettings()
  const rules: KeyRules = {
    requiresKey: (kind) => providers.find((p) => p.kind === kind)?.api_key === 'required',
    hasSavedKey: (kind, baseUrl) =>
      settings.providers.some((p) => p.kind === kind && p.api_key_set && p.base_url === baseUrl),
  }
  const form = useForm<LanguageModelValues, KeyRules>({
    resolver,
    context: rules,
    defaultValues: valuesFor(settings.active, providers, settings),
    mode: 'onTouched',
  })
  const [showKey, setShowKey] = useState(false)
  const [confirmReset, setConfirmReset] = useState(false)
  const [notice, setNotice] = useState<string>()

  const models = api.useMutation('post', '/v1/llm/models')
  const test = api.useMutation('post', '/v1/llm/test')
  const save = api.useMutation('put', '/v1/llm/settings')
  const reset = api.useMutation('delete', '/v1/llm/settings')

  const [kind, baseUrl, model] = useWatch({
    control: form.control,
    name: ['kind', 'base_url', 'model'],
  })
  const provider = providers.find((p) => p.kind === kind)
  const savedKey = settings.providers.find((p) => p.kind === kind && p.api_key_set)
  const keyReusable = savedKey?.base_url === normalizeUrl(baseUrl)
  const { errors } = form.formState

  function clearResults() {
    for (const mutation of [models, test, save, reset]) mutation.reset()
    setNotice(undefined)
  }

  function choose(next: ProviderKind) {
    form.reset(valuesFor(next, providers, settings))
    setShowKey(false)
    clearResults()
  }

  function connection(values: LanguageModelValues) {
    return {
      kind: values.kind,
      base_url: values.base_url.trim(),
      api_key: keyToSend(values.api_key),
    }
  }

  async function loadModels() {
    clearResults()
    if (!(await form.trigger(['base_url', 'api_key']))) return
    models.mutate({ body: connection(form.getValues()) })
  }

  const runTest = form.handleSubmit((values) => {
    clearResults()
    test.mutate({ body: { ...connection(values), model: values.model.trim() } })
  })

  const onSubmit = form.handleSubmit((values) => {
    clearResults()
    save.mutate(
      { body: { ...connection(values), model: values.model.trim() } },
      {
        onSuccess: (saved) => {
          setSettings(saved)
          form.reset({ ...values, api_key: '' })
          setNotice(`Saved. ${provider?.label ?? values.kind} is now the active provider.`)
        },
      },
    )
  })

  function resetAll() {
    clearResults()
    setConfirmReset(false)
    reset.mutate(
      {},
      {
        onSuccess: (restored) => {
          setSettings(restored)
          form.reset(valuesFor(restored.active, providers, restored))
          setNotice('Back to the defaults from the environment. Saved keys were deleted.')
        },
      },
    )
  }

  const busy = models.isPending || test.isPending || save.isPending || reset.isPending
  const failure = describeFailure()

  function describeFailure() {
    if (test.data && !test.data.ok) return { title: 'The test failed', message: test.data.error }
    if (test.isError) return { title: 'The test failed', message: errorMessage(test.error) }
    if (save.isError) return { title: 'Could not save', message: errorMessage(save.error) }
    if (reset.isError) return { title: 'Could not reset', message: errorMessage(reset.error) }
    return undefined
  }

  return (
    <form onSubmit={(event) => void onSubmit(event)} noValidate className="flex flex-col gap-6">
      <ProviderPicker providers={providers} settings={settings} value={kind} onChange={choose} />

      <div className="grid gap-5 md:grid-cols-2">
        <Field label="Base URL" hint={provider?.base_url_hint} error={errors.base_url?.message}>
          {(control) => (
            <Input
              inputMode="url"
              autoComplete="off"
              spellCheck={false}
              placeholder={provider?.default_base_url || 'https://…'}
              {...control}
              {...form.register('base_url')}
            />
          )}
        </Field>

        <Field
          label={provider?.api_key === 'required' ? 'API key' : 'API key (optional)'}
          hint={
            keyReusable
              ? `Saved key ending in ${savedKey.api_key_hint ?? '••••'}. Leave empty to keep it.`
              : savedKey
                ? 'The URL changed: enter the key again for this server.'
                : provider?.api_key_url && (
                    <a
                      href={provider.api_key_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-primary inline-flex items-center gap-1 underline-offset-4 hover:underline"
                    >
                      Get a key <ExternalLink className="size-3" aria-hidden="true" />
                    </a>
                  )
          }
          error={errors.api_key?.message}
        >
          {(control) => (
            <div className="relative">
              <Input
                type={showKey ? 'text' : 'password'}
                autoComplete="off"
                spellCheck={false}
                placeholder={keyReusable ? '••••••••••••' : 'Paste your key'}
                className="pr-10"
                {...control}
                {...form.register('api_key')}
              />
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                className="absolute top-1/2 right-1 -translate-y-1/2"
                aria-label={showKey ? 'Hide the key' : 'Show the key'}
                onClick={() => {
                  setShowKey((shown) => !shown)
                }}
              >
                {showKey ? <EyeOff /> : <Eye />}
              </Button>
            </div>
          )}
        </Field>
      </div>

      <ModelPicker
        error={errors.model?.message}
        register={form.register('model')}
        models={models.data?.models}
        loading={models.isPending}
        loadError={models.isError ? errorMessage(models.error) : undefined}
        onLoad={() => void loadModels()}
        onPick={(id) => {
          form.setValue('model', id, { shouldValidate: true, shouldDirty: true })
        }}
        current={model}
        disabled={busy}
      />

      <AnimatePresence mode="popLayout">
        {test.data?.ok && (
          <m.div key="test-ok" {...reveal}>
            <Alert>
              <CheckCircle2 className="text-success" />
              <AlertTitle>Connected in {test.data.latency_ms} ms</AlertTitle>
              {test.data.reply && <AlertDescription>“{test.data.reply}”</AlertDescription>}
            </Alert>
          </m.div>
        )}
        {failure && (
          <m.div key="failure" {...reveal}>
            <Alert variant="destructive">
              <XCircle />
              <AlertTitle>{failure.title}</AlertTitle>
              <AlertDescription>{failure.message}</AlertDescription>
            </Alert>
          </m.div>
        )}
        {notice && (
          <m.p key="notice" {...reveal} role="status" className="text-success text-sm font-medium">
            {notice}
          </m.p>
        )}
      </AnimatePresence>

      <div className="flex flex-col-reverse gap-3 border-t pt-5 sm:flex-row sm:items-center">
        {confirmReset ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-muted-foreground text-sm">Delete saved settings and keys?</span>
            <Button type="button" variant="destructive" size="sm" onClick={resetAll}>
              Yes, reset
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                setConfirmReset(false)
              }}
            >
              Cancel
            </Button>
          </div>
        ) : (
          <Button
            type="button"
            variant="ghost"
            disabled={busy || settings.source === 'environment'}
            onClick={() => {
              setConfirmReset(true)
            }}
          >
            <ListRestart /> Reset to defaults
          </Button>
        )}
        <div className="flex flex-col gap-3 sm:ml-auto sm:flex-row">
          <Button type="button" variant="outline" disabled={busy} onClick={() => void runTest()}>
            {test.isPending ? <Loader2 className="animate-spin" /> : <PlugZap />}
            Test connection
          </Button>
          <Button type="submit" disabled={busy}>
            {save.isPending ? <Loader2 className="animate-spin" /> : <Save />}
            Save and use
          </Button>
        </div>
      </div>

      {settings.source === 'environment' && (
        <p className="text-muted-foreground -mt-2 flex items-center gap-1.5 text-xs">
          <RotateCcw className="size-3" aria-hidden="true" />
          Using the defaults from the environment (<code>VT_LLM_*</code>) until you save.
        </p>
      )}
    </form>
  )
}

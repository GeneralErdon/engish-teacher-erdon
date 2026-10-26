import { vi, type Mock } from 'vitest'

import type { Schemas } from '@/lib/api/client'

type Settings = Schemas['LlmSettingsView']
type Kind = Schemas['ProviderKind']

export const PROVIDERS: Schemas['ProviderInfo'][] = [
  {
    kind: 'ollama',
    label: 'Ollama',
    description: 'Open models running on this computer with Ollama. Free and private.',
    protocol: 'ollama',
    default_base_url: 'http://localhost:11434',
    base_url_hint: 'From the Docker api, use http://host.docker.internal:11434',
    api_key: 'optional',
    api_key_url: null,
    suggested_model: '',
  },
  {
    kind: 'ollama_cloud',
    label: 'Ollama Cloud',
    description: 'Large open models hosted by Ollama. Free tier with usage limits.',
    protocol: 'ollama',
    default_base_url: 'https://ollama.com',
    base_url_hint: 'https://ollama.com',
    api_key: 'required',
    api_key_url: 'https://ollama.com/settings/keys',
    suggested_model: '',
  },
  {
    kind: 'anthropic',
    label: 'Anthropic',
    description: 'Claude models through the Anthropic API. Paid per token.',
    protocol: 'anthropic',
    default_base_url: 'https://api.anthropic.com',
    base_url_hint: 'Without /v1',
    api_key: 'required',
    api_key_url: 'https://platform.claude.com/settings/keys',
    suggested_model: 'claude-opus-5-5',
  },
  {
    kind: 'openai_compatible',
    label: 'OpenAI-compatible',
    description: 'Any server that speaks the OpenAI Chat Completions API.',
    protocol: 'openai',
    default_base_url: '',
    base_url_hint: 'Usually ends in /v1',
    api_key: 'optional',
    api_key_url: null,
    suggested_model: '',
  },
]

export const ENVIRONMENT: Settings = {
  active: 'openai_compatible',
  source: 'environment',
  providers: [
    {
      kind: 'openai_compatible',
      base_url: 'http://llm:8080/v1',
      model: 'gemma-3-4b-it-q4',
      api_key_set: false,
      api_key_hint: null,
    },
  ],
}

const STT_DEFAULT = 'Systran/faster-distil-whisper-small.en'
const STT_GPU_DEFAULT = 'ggerganov/whisper.cpp/ggml-small.en-q8_0.bin'
const TTS_DEFAULT = 'speaches-ai/Kokoro-82M-v1.0-ONNX'

const entry = (
  fields: Pick<Schemas['SpeechModel'], 'key' | 'kind' | 'model_id' | 'label' | 'approx_mb'> &
    Partial<Schemas['SpeechModel']>,
): Schemas['SpeechModel'] => ({
  engine: 'openai',
  hint: 'A good balance.',
  english_only: true,
  state: 'available',
  download: null,
  default: false,
  selected: false,
  from_configuration: false,
  ms_per_audio_s: null,
  ...fields,
})

/** The catalogue as a fresh install sees it: the defaults installed and in use. */
export const SPEECH_MODELS: Schemas['SpeechModels'] = {
  recognition_manageable: true,
  voice_manageable: true,
  engines: [
    { engine: 'openai', running: true, manageable: true },
    { engine: 'whispercpp', running: false, manageable: true },
  ],
  last_error: null,
  models: [
    entry({
      key: 'whisper-small-en',
      kind: 'recognition',
      model_id: STT_DEFAULT,
      label: 'Whisper small (English)',
      approx_mb: 250,
      state: 'installed',
      default: true,
      selected: true,
    }),
    entry({
      key: 'whisper-base',
      kind: 'recognition',
      model_id: 'Systran/faster-whisper-base',
      label: 'Whisper base',
      approx_mb: 145,
      english_only: false,
      state: 'installed',
    }),
    entry({
      key: 'whisper-tiny-en',
      kind: 'recognition',
      model_id: 'Systran/faster-whisper-tiny.en',
      label: 'Whisper tiny (English)',
      approx_mb: 75,
    }),
    entry({
      key: 'kokoro',
      kind: 'voice',
      model_id: TTS_DEFAULT,
      label: 'Kokoro',
      approx_mb: 330,
      state: 'installed',
      default: true,
      selected: true,
    }),
    entry({
      key: 'piper-lessac',
      kind: 'voice',
      model_id: 'speaches-ai/piper-en_US-lessac-medium',
      label: 'Piper Lessac',
      approx_mb: 60,
    }),
  ],
}

export const VOICES: Schemas['Voice'][] = [
  { id: 'af_heart', name: 'Heart', accent: 'american', gender: 'female' },
  { id: 'am_michael', name: 'Michael', accent: 'american', gender: 'male' },
  { id: 'bf_emma', name: 'Emma', accent: 'british', gender: 'female' },
  { id: 'bm_george', name: 'George', accent: 'british', gender: 'male' },
]

type Reply = Response | (() => Response | Promise<Response>)

interface Overrides {
  health?: Reply
  speech?: Reply
  learner?: Reply
  saveLearner?: Reply
  providers?: Reply
  settings?: Reply
  models?: Reply
  test?: Reply
  save?: Reply
  reset?: Reply
  speechSettings?: Reply
  speechModels?: Reply
  voices?: Reply
  preview?: Reply
}

export interface FakeApi {
  fetch: Mock<(request: Request) => Promise<Response>>
  learner: Schemas['LearnerProfileView']
  speech: Schemas['SpeechStatus']
  /** Bodies the UI sent, by "METHOD /path". */
  sent: Map<string, unknown[]>
  settings: Settings
  speechSettings: Schemas['SpeechSettingsView']
  speechModels: Schemas['SpeechModels']
  voices: Schemas['Voice'][]
  /** Keys of downloads the fake moves on with every poll of the catalogue. */
  advancing: Set<string>
}

const json = (body: unknown, status = 200) => Response.json(body, { status })

/** A stand-in for the api: `fetch` answers like the real routes, with state for the settings. */
export function fakeApi(overrides: Overrides = {}): FakeApi {
  const sent = new Map<string, unknown[]>()
  const api: FakeApi = {
    fetch: vi.fn<(request: Request) => Promise<Response>>(),
    sent,
    settings: structuredClone(ENVIRONMENT),
    speechSettings: {
      stt_model: STT_DEFAULT,
      stt_engine: 'openai',
      stt_gpu_model: STT_GPU_DEFAULT,
      tts_model: TTS_DEFAULT,
      tts_voice: 'af_heart',
      tts_speed: 0.95,
      max_turn_s: 120,
      source: 'environment',
      missing: [],
      pending: [],
    },
    speechModels: structuredClone(SPEECH_MODELS),
    voices: structuredClone(VOICES),
    advancing: new Set(),
    learner: { level: 'B1', explanations: 'native', native_language: 'es', source: 'environment' },
    speech: {
      recognition: {
        base_url: 'http://localhost:8000/v1',
        model: 'Systran/faster-distil-whisper-small.en',
        reachable: true,
        model_ready: true,
        detail: null,
      },
      synthesis: {
        base_url: 'http://localhost:8000/v1',
        model: 'speaches-ai/Kokoro-82M-v1.0-ONNX',
        reachable: true,
        model_ready: true,
        detail: null,
      },
    },
  }

  const reply = (override: Reply | undefined, fallback: () => Response | Promise<Response>) => {
    if (override === undefined) return fallback()
    return typeof override === 'function' ? override() : override.clone()
  }

  const setModel = (key: string, change: Partial<Schemas['SpeechModel']>) => {
    api.speechModels.models = api.speechModels.models.map((m) =>
      m.key === key ? { ...m, ...change } : m,
    )
  }
  const select = (kind: Schemas['SpeechKind'], modelId: string) => {
    api.speechModels.models = api.speechModels.models.map((m) =>
      m.kind === kind ? { ...m, selected: m.model_id === modelId } : m,
    )
  }
  /** Each poll of the catalogue moves a running download on; the second one finishes it. */
  const advanceDownloads = () => {
    for (const model of api.speechModels.models) {
      if (!api.advancing.has(model.key)) continue
      const total = model.download?.total_bytes ?? 100
      const done = (model.download?.done_bytes ?? 0) + total / 2
      if (done < total) {
        setModel(model.key, { download: { done_bytes: done, total_bytes: total } })
        continue
      }
      api.advancing.delete(model.key)
      setModel(model.key, { state: 'installed', download: null })
      const wanted = api.speechSettings.pending.includes(model.model_id)
      if (wanted) {
        api.speechSettings.pending = api.speechSettings.pending.filter(
          (id) => id !== model.model_id,
        )
        const field = model.kind === 'recognition' ? 'stt_model' : 'tts_model'
        api.speechSettings[field] = model.model_id
        select(model.kind, model.model_id)
      }
    }
  }

  api.fetch.mockImplementation(async (request: Request) => {
    const { pathname } = new URL(request.url)
    const route = `${request.method} ${pathname}`
    if (request.method !== 'GET') {
      const body: unknown = await request.json().catch(() => undefined)
      sent.set(route, [...(sent.get(route) ?? []), body])
    }
    switch (route) {
      case 'GET /healthz':
        return reply(overrides.health, () =>
          json({ status: 'ok', service: 'api', version: '0.1.0' }),
        )
      case 'GET /v1/speech/status':
        return reply(overrides.speech, () => json(api.speech))
      case 'GET /v1/learner':
        return reply(overrides.learner, () => json(api.learner))
      case 'PUT /v1/learner':
        return reply(overrides.saveLearner, () => {
          const body = sent.get(route)?.at(-1) as Schemas['LearnerProfile']
          api.learner = { ...api.learner, ...body, source: 'saved' }
          return json(api.learner)
        })
      case 'GET /v1/llm/providers':
        return reply(overrides.providers, () => json(PROVIDERS))
      case 'GET /v1/llm/settings':
        return reply(overrides.settings, () => json(api.settings))
      case 'POST /v1/llm/models':
        return reply(overrides.models, () =>
          json({ models: ['gemma4:31b', 'gpt-oss:120b', 'qwen3:8b'] }),
        )
      case 'POST /v1/llm/test':
        return reply(overrides.test, () =>
          json({ ok: true, latency_ms: 842, reply: 'Hello! Ready to practise?', error: null }),
        )
      case 'PUT /v1/llm/settings':
        return reply(overrides.save, () => {
          const body = sent.get(route)?.at(-1) as {
            kind: Kind
            base_url: string
            model: string
            api_key: string | null
          }
          const others = api.settings.source === 'saved' ? api.settings.providers : []
          api.settings = {
            active: body.kind,
            source: 'saved',
            providers: [
              ...others.filter((p) => p.kind !== body.kind),
              {
                kind: body.kind,
                base_url: body.base_url,
                model: body.model,
                api_key_set: body.api_key !== null && body.api_key !== '',
                api_key_hint: body.api_key ? `…${body.api_key.slice(-4)}` : null,
              },
            ],
          }
          return json(api.settings)
        })
      case 'DELETE /v1/llm/settings':
        return reply(overrides.reset, () => {
          api.settings = structuredClone(ENVIRONMENT)
          return json(api.settings)
        })
      case 'GET /v1/speech/settings':
        return reply(overrides.speechSettings, () => json(api.speechSettings))
      case 'PUT /v1/speech/settings': {
        const body = sent.get(route)?.at(-1) as Schemas['SpeechSettings']
        api.speechSettings = { ...api.speechSettings, ...body, source: 'saved' }
        select('recognition', body.stt_model)
        select('voice', body.tts_model)
        return json(api.speechSettings)
      }
      case 'GET /v1/speech/models':
        return reply(overrides.speechModels, () => {
          advanceDownloads()
          return json(api.speechModels)
        })
      case 'GET /v1/speech/voices':
        return reply(overrides.voices, () => json(api.voices))
      case 'POST /v1/speech/preview':
        return reply(
          overrides.preview,
          () => new Response(new Blob(['RIFF']), { headers: { 'Content-Type': 'audio/wav' } }),
        )
      default: {
        const download = /^\/v1\/speech\/models\/([^/]+)\/download$/.exec(pathname)
        const uninstall = /^\/v1\/speech\/models\/([^/]+)$/.exec(pathname)
        if (download && request.method === 'POST') {
          const model = api.speechModels.models.find((m) => m.key === download[1])
          if (!model) return json({ detail: 'Unknown model' }, 404)
          const body = sent.get(route)?.at(-1) as { activate: boolean }
          setModel(model.key, {
            state: 'downloading',
            download: { done_bytes: 0, total_bytes: 100 },
          })
          api.advancing.add(model.key)
          if (body.activate) api.speechSettings.pending = [model.model_id]
          return json(api.speechModels, 202)
        }
        if (download && request.method === 'DELETE') {
          api.advancing.delete(download[1] ?? '')
          setModel(download[1] ?? '', { state: 'available', download: null })
          api.speechSettings.pending = []
          return new Response(null, { status: 204 })
        }
        if (uninstall && request.method === 'DELETE') {
          setModel(uninstall[1] ?? '', { state: 'available' })
          return new Response(null, { status: 204 })
        }
        return json({ detail: 'Not Found' }, 404)
      }
    }
  })
  return api
}

/** `fetch` rejects like it does when nothing listens on the port. */
export const unreachable = (): Promise<Response> => Promise.reject(new TypeError('Failed to fetch'))

/** Never answers: the UI stays in its loading state. */
export const pending = (): Promise<Response> => new Promise(() => undefined)

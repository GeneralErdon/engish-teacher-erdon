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

type Reply = Response | (() => Response | Promise<Response>)

interface Overrides {
  health?: Reply
  providers?: Reply
  settings?: Reply
  models?: Reply
  test?: Reply
  save?: Reply
  reset?: Reply
}

export interface FakeApi {
  fetch: Mock<(request: Request) => Promise<Response>>
  /** Bodies the UI sent, by "METHOD /path". */
  sent: Map<string, unknown[]>
  settings: Settings
}

const json = (body: unknown, status = 200) => Response.json(body, { status })

/** A stand-in for the api: `fetch` answers like the real routes, with state for the settings. */
export function fakeApi(overrides: Overrides = {}): FakeApi {
  const sent = new Map<string, unknown[]>()
  const api: FakeApi = {
    fetch: vi.fn<(request: Request) => Promise<Response>>(),
    sent,
    settings: structuredClone(ENVIRONMENT),
  }

  const reply = (override: Reply | undefined, fallback: () => Response | Promise<Response>) => {
    if (override === undefined) return fallback()
    return typeof override === 'function' ? override() : override.clone()
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
      default:
        return json({ detail: 'Not Found' }, 404)
    }
  })
  return api
}

/** `fetch` rejects like it does when nothing listens on the port. */
export const unreachable = (): Promise<Response> => Promise.reject(new TypeError('Failed to fetch'))

/** Never answers: the UI stays in its loading state. */
export const pending = (): Promise<Response> => new Promise(() => undefined)

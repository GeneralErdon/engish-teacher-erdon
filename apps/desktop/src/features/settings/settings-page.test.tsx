import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { fakeApi, pending } from '@/test/fake-api'
import { renderApp } from '@/test/render-app'

const failure = (status: number, detail: unknown) => () => Response.json({ detail }, { status })

async function openSettings(api = fakeApi()) {
  const view = renderApp('/settings', api)
  await screen.findByRole('radiogroup', { name: 'Provider' })
  return view
}

const field = (name: RegExp | string) => screen.getByLabelText(name)

describe('Language model settings', () => {
  it('starts from the environment and marks the active provider', async () => {
    await openSettings()

    const active = screen.getByRole('radio', { name: /OpenAI-compatible/ })
    expect(active).toBeChecked()
    expect(within(active).getByText('Active')).toBeInTheDocument()
    expect(field('Base URL')).toHaveValue('http://llm:8080/v1')
    expect(field('Model')).toHaveValue('gemma-3-4b-it-q4')
    expect(screen.getByText(/until you save/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /reset to defaults/i })).toBeDisabled()
  })

  it('sets up Ollama Cloud end to end: key, model list, test, save', async () => {
    const { user, api } = await openSettings()

    await user.click(screen.getByRole('radio', { name: /Ollama Cloud/ }))
    expect(field('Base URL')).toHaveValue('https://ollama.com')
    expect(screen.getByRole('link', { name: /get a key/i })).toHaveAttribute(
      'href',
      'https://ollama.com/settings/keys',
    )

    // A required key is checked before anything is sent.
    await user.click(screen.getByRole('button', { name: /load models/i }))
    expect(await screen.findByText('This provider needs an API key.')).toBeInTheDocument()
    expect(api.sent.has('POST /v1/llm/models')).toBe(false)

    await user.type(field('API key'), 'secret-key-1234')
    await user.click(screen.getByRole('button', { name: /load models/i }))
    const list = await screen.findByRole('list', { name: 'Available models' })
    expect(api.sent.get('POST /v1/llm/models')).toEqual([
      { kind: 'ollama_cloud', base_url: 'https://ollama.com', api_key: 'secret-key-1234' },
    ])
    expect(screen.getByText('3 models available.')).toBeInTheDocument()

    // Typing filters the list; picking fills the field.
    await user.type(field('Model'), 'gpt')
    expect(within(list).getAllByRole('button')).toHaveLength(1)
    await user.click(within(list).getByRole('button', { name: 'gpt-oss:120b' }))
    expect(field('Model')).toHaveValue('gpt-oss:120b')
    expect(within(list).getAllByRole('button')).toHaveLength(3)

    await user.click(screen.getByRole('button', { name: /test connection/i }))
    expect(await screen.findByText('Connected in 842 ms')).toBeInTheDocument()
    expect(screen.getByText('“Hello! Ready to practise?”')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /save and use/i }))
    expect(
      await screen.findByText('Saved. Ollama Cloud is now the active provider.'),
    ).toBeInTheDocument()
    expect(api.sent.get('PUT /v1/llm/settings')).toEqual([
      {
        kind: 'ollama_cloud',
        base_url: 'https://ollama.com',
        api_key: 'secret-key-1234',
        model: 'gpt-oss:120b',
      },
    ])
    expect(
      within(screen.getByRole('radio', { name: /Ollama Cloud/ })).getByText('Active'),
    ).toBeInTheDocument()
    // The key is gone from the form; the api keeps it.
    expect(field('API key')).toHaveValue('')
    expect(screen.getByText(/Saved key ending in …1234/)).toBeInTheDocument()
  })

  it('reuses a saved key, unless the URL changes', async () => {
    const api = fakeApi()
    api.settings = {
      active: 'anthropic',
      source: 'saved',
      providers: [
        {
          kind: 'anthropic',
          base_url: 'https://api.anthropic.com',
          model: 'claude-opus-5-5',
          api_key_set: true,
          api_key_hint: '…abcd',
        },
        {
          kind: 'ollama',
          base_url: 'http://localhost:11434',
          model: 'gemma3',
          api_key_set: false,
          api_key_hint: null,
        },
      ],
    }
    const { user } = await openSettings(api)

    expect(
      within(screen.getByRole('radio', { name: /^Ollama(?!\s?Cloud)/ })).getByText('Saved'),
    ).toBeInTheDocument()
    expect(screen.getByText(/Saved key ending in …abcd/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /test connection/i }))
    await screen.findByText('Connected in 842 ms')
    expect(api.sent.get('POST /v1/llm/test')?.[0]).toMatchObject({ api_key: null })

    await user.clear(field('Base URL'))
    await user.type(field('Base URL'), 'https://proxy.example')
    expect(screen.getByText(/enter the key again/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /save and use/i }))
    expect(await screen.findByText('This provider needs an API key.')).toBeInTheDocument()
  })

  it('validates the URL and the model name', async () => {
    const { user } = await openSettings()

    await user.clear(field('Base URL'))
    await user.type(field('Base URL'), 'ftp://example.com')
    await user.clear(field('Model'))
    await user.type(field('Model'), 'two words')
    await user.click(screen.getByRole('button', { name: /save and use/i }))

    expect(await screen.findByText('Enter an http:// or https:// URL.')).toBeInTheDocument()
    expect(screen.getByText('Model names have no spaces.')).toBeInTheDocument()
    expect(field('Model')).toHaveAttribute('aria-invalid', 'true')

    await user.clear(field('Base URL'))
    await user.clear(field('Model'))
    await user.click(screen.getByRole('button', { name: /save and use/i }))
    expect(await screen.findByText('Enter the base URL.')).toBeInTheDocument()
    expect(screen.getByText('Pick or type a model.')).toBeInTheDocument()
  })

  it('reports failed tests, model lists and saves', async () => {
    const api = fakeApi({
      test: () =>
        Response.json({
          ok: false,
          latency_ms: null,
          reply: null,
          error: 'The provider rejected the API key (HTTP 401).',
        }),
      models: failure(502, 'Could not connect to http://llm:8080/v1.'),
      save: failure(422, [{ msg: 'Value error, bad thing' }]),
    })
    const { user } = await openSettings(api)

    await user.click(screen.getByRole('button', { name: /test connection/i }))
    expect(await screen.findByText('The test failed')).toBeInTheDocument()
    expect(screen.getByText('The provider rejected the API key (HTTP 401).')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /load models/i }))
    expect(await screen.findByText('Could not connect to http://llm:8080/v1.')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /save and use/i }))
    expect(await screen.findByText('Could not save')).toBeInTheDocument()
    expect(screen.getByText('Value error, bad thing')).toBeInTheDocument()
  })

  it('reports a failed reset', async () => {
    const api = fakeApi({ reset: failure(500, 'disk full') })
    api.settings = { ...api.settings, source: 'saved' }
    const { user } = await openSettings(api)

    await user.click(screen.getByRole('button', { name: /reset to defaults/i }))
    await user.click(screen.getByRole('button', { name: 'Yes, reset' }))

    expect(await screen.findByText('Could not reset')).toBeInTheDocument()
    expect(screen.getByText('disk full')).toBeInTheDocument()
  })

  it.each([
    ['models', /load models/i],
    ['test', /test connection/i],
    ['save', /save and use/i],
  ] as const)('blocks other actions while %s runs', async (action, button) => {
    const { user } = await openSettings(fakeApi({ [action]: pending }))

    await user.click(screen.getByRole('button', { name: button }))

    expect(screen.getByRole('button', { name: /test connection/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /save and use/i })).toBeDisabled()
  })

  it('copes with a provider this UI does not know (an older UI on a newer api)', async () => {
    const api = fakeApi()
    api.settings = { active: 'gemini', source: 'saved', providers: [] }
    const { user } = await openSettings(api)

    expect(field('Base URL')).toHaveValue('')
    await user.type(field('Base URL'), 'https://g.example')
    await user.type(field('Model'), 'gemini-3.8-flash')
    await user.click(screen.getByRole('button', { name: /save and use/i }))

    expect(await screen.findByText('Saved. gemini is now the active provider.')).toBeInTheDocument()
  })

  it('treats a network failure during a test as a failed test', async () => {
    const { user } = await openSettings(
      fakeApi({ test: () => Promise.reject(new TypeError('Failed to fetch')) }),
    )

    await user.click(screen.getByRole('button', { name: /test connection/i }))

    expect(await screen.findByText('Could not reach the api. Is it running?')).toBeInTheDocument()
  })

  it('resets to the environment after confirming', async () => {
    const api = fakeApi()
    api.settings = {
      active: 'ollama',
      source: 'saved',
      providers: [
        {
          kind: 'ollama',
          base_url: 'http://localhost:11434',
          model: 'gemma3',
          api_key_set: false,
          api_key_hint: null,
        },
      ],
    }
    const { user } = await openSettings(api)

    await user.click(screen.getByRole('button', { name: /reset to defaults/i }))
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(api.sent.has('DELETE /v1/llm/settings')).toBe(false)

    await user.click(screen.getByRole('button', { name: /reset to defaults/i }))
    await user.click(screen.getByRole('button', { name: 'Yes, reset' }))

    expect(await screen.findByText(/Back to the defaults/)).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /OpenAI-compatible/ })).toBeChecked()
    expect(field('Model')).toHaveValue('gemma-3-4b-it-q4')
  })

  it('shows and hides the key', async () => {
    const { user } = await openSettings()

    expect(field('API key (optional)')).toHaveAttribute('type', 'password')
    await user.click(screen.getByRole('button', { name: 'Show the key' }))
    expect(field('API key (optional)')).toHaveAttribute('type', 'text')
    await user.click(screen.getByRole('button', { name: 'Hide the key' }))
    expect(field('API key (optional)')).toHaveAttribute('type', 'password')
  })

  it('fills in the suggested model and keeps typed names that are not listed', async () => {
    const { user } = await openSettings()

    await user.click(screen.getByRole('radio', { name: /^Anthropic/ }))
    expect(field('Model')).toHaveValue('claude-opus-5-5')

    await user.type(field('API key'), 'k')
    await user.click(screen.getByRole('button', { name: /load models/i }))
    await screen.findByText(/models available|No listed model/)
    expect(
      screen.getByText('No listed model matches: the name will be used as typed.'),
    ).toBeInTheDocument()
  })

  it('explains when the settings cannot be loaded, and retries', async () => {
    const api = fakeApi({ settings: failure(500, 'boom') })
    const { user } = renderApp('/settings', api)

    expect(await screen.findByText('Could not load the model settings')).toBeInTheDocument()
    expect(screen.getByText('boom')).toBeInTheDocument()

    api.fetch.mockClear()
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(api.fetch).toHaveBeenCalled()
  })

  it('reports a provider catalogue failure too', async () => {
    renderApp('/settings', fakeApi({ providers: failure(503, 'starting') }))

    expect(await screen.findByText('starting')).toBeInTheDocument()
  })

  it('shows placeholders while loading', async () => {
    renderApp('/settings', fakeApi({ settings: pending }))

    expect(await screen.findByLabelText('Loading')).toBeInTheDocument()
  })
})

describe('Appearance and backend settings', () => {
  it('picks the theme', async () => {
    const { user } = await openSettings()
    const theme = screen.getByRole('radiogroup', { name: 'Theme' })

    await user.click(within(theme).getByRole('radio', { name: 'Dark' }))
    expect(document.documentElement).toHaveClass('dark')

    await user.click(within(theme).getByRole('radio', { name: 'Light' }))
    expect(document.documentElement).not.toHaveClass('dark')

    await user.click(within(theme).getByRole('radio', { name: 'System' }))
    expect(within(theme).getByRole('radio', { name: 'System' })).toBeChecked()
  })

  it('shows where the backend is', async () => {
    await openSettings()

    expect(screen.getByText('http://localhost:8080')).toBeInTheDocument()
  })
})

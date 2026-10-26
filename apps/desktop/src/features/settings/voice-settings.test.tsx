import { screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { fakeApi, type FakeApi } from '@/test/fake-api'
import { renderApp } from '@/test/render-app'

import { playPreview } from './use-speech'

const failure = (status: number, detail: string) => () => Response.json({ detail }, { status })

const played: string[] = []
class FakeAudio {
  static ended: (() => void) | undefined
  readonly src: string
  constructor(src: string) {
    this.src = src
  }
  addEventListener(_type: string, listener: () => void) {
    FakeAudio.ended = listener
  }
  play() {
    played.push(this.src)
    return Promise.resolve()
  }
}

beforeEach(() => {
  played.length = 0
  vi.stubGlobal('Audio', FakeAudio)
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:preview')
  URL.revokeObjectURL = vi.fn()
})
afterEach(() => {
  vi.restoreAllMocks()
})

const recognition = () => screen.findByRole('radiogroup', { name: 'Speech recognition model' })
const voiceModels = () => screen.findByRole('radiogroup', { name: 'Voice model' })

const row = (list: HTMLElement, label: string) => {
  const radio = within(list).getByRole('radio', { name: label })
  const card = radio.closest('div.rounded-lg')
  if (!(card instanceof HTMLElement)) throw new Error('no row')
  return within(card)
}

const LESSAC = 'speaches-ai/piper-en_US-lessac-medium'

/** How many times the readiness rows asked `GET /v1/speech/status`. */
const statusChecks = (api: FakeApi) =>
  api.fetch.mock.calls.filter(([request]) => new URL(request.url).pathname === '/v1/speech/status')
    .length

/** `fetch` that holds the requests `matches` picks until `release()`. */
function holding(api: FakeApi, matches: (request: Request) => boolean) {
  let release: () => void = () => undefined
  const held = new Promise<void>((resolve) => {
    release = resolve
  })
  vi.stubGlobal('fetch', async (request: Request) => {
    if (matches(request)) await held
    return api.fetch(request)
  })
  return () => {
    release()
  }
}

function measured(api: FakeApi, msPerAudioS: number | null) {
  api.speechModels.models = api.speechModels.models.map((m) =>
    m.key === 'whisper-small-en' ? { ...m, ms_per_audio_s: msPerAudioS } : m,
  )
}

describe('Speech recognition models', () => {
  it('lists recognition models with their state and size', async () => {
    const api = fakeApi()
    api.speechModels.models = api.speechModels.models.map((m) =>
      m.key === 'whisper-base'
        ? { ...m, state: 'downloading', download: { done_bytes: 36, total_bytes: 144 } }
        : m,
    )
    renderApp('/settings', api)
    const list = await recognition()

    const small = row(list, 'Whisper small (English)')
    expect(small.getByText('Default')).toBeInTheDocument()
    expect(small.getByText('In use')).toBeInTheDocument()
    expect(small.getByText(/250 MB · English only/)).toBeInTheDocument()
    expect(
      row(list, 'Whisper tiny (English)').getByRole('button', { name: 'Download (75 MB)' }),
    ).toBeInTheDocument()
    expect(
      within(list).getByRole('progressbar', { name: 'Downloading Whisper base: 25%' }),
    ).toHaveAttribute('aria-valuenow', '25')
    expect(row(list, 'Whisper base').getByText(/Multilingual/)).toBeInTheDocument()
  })

  it('selecting a model that is not installed downloads it and shows progress', async () => {
    const { user, api } = renderApp('/settings')
    const list = await recognition()
    await screen.findAllByLabelText('Ready')
    const checked = statusChecks(api)

    await user.click(within(list).getByRole('radio', { name: 'Whisper tiny (English)' }))
    const tiny = row(list, 'Whisper tiny (English)')
    expect(api.sent.has('POST /v1/speech/models/whisper-tiny-en/download')).toBe(false)
    expect(tiny.getByText('Download 75 MB and use it?')).toBeInTheDocument()
    await user.click(tiny.getByRole('button', { name: 'Download' }))

    expect(api.sent.get('POST /v1/speech/models/whisper-tiny-en/download')).toEqual([
      { activate: true },
    ])
    expect(
      await within(list).findByRole('progressbar', { name: /Downloading Whisper tiny/ }),
    ).toBeInTheDocument()
    expect(await row(list, 'Whisper tiny (English)').findByText(/Will be used when/)).toBeVisible()
    await waitFor(
      () => {
        expect(row(list, 'Whisper tiny (English)').getByText('In use')).toBeInTheDocument()
      },
      { timeout: 5000 },
    )
    expect(row(list, 'Whisper small (English)').queryByText('In use')).not.toBeInTheDocument()
    await waitFor(() => {
      expect(screen.queryByText(/Will be used when/)).not.toBeInTheDocument()
    })
    await waitFor(() => {
      expect(statusChecks(api)).toBeGreaterThan(checked) // the readiness rows follow the model
    })
  })

  it('arrowing over rows starts no download', async () => {
    const { user, api } = renderApp('/settings')
    const list = await recognition()
    within(list).getByRole('radio', { name: 'Whisper small (English)' }).focus()

    // Radix selects the row that arrow focus lands on, but only while the key is held down.
    await user.keyboard('{ArrowDown>}')
    await waitFor(() => {
      expect(within(list).getByRole('radio', { name: 'Whisper base' })).toBeChecked()
    })
    await user.keyboard('{/ArrowDown}{ArrowDown>}')

    expect(await screen.findByText('Download 75 MB and use it?')).toBeInTheDocument()
    await user.keyboard('{/ArrowDown}')
    expect([...api.sent.keys()].filter((route) => route.startsWith('POST'))).toEqual([])
    expect(within(list).getByRole('radio', { name: 'Whisper tiny (English)' })).toBeChecked()
  })

  it('cancelling the proposal sends nothing and restores the model in use', async () => {
    const { user, api } = renderApp('/settings')
    const list = await recognition()
    await user.click(within(list).getByRole('radio', { name: 'Whisper tiny (English)' }))

    await user.click(row(list, 'Whisper tiny (English)').getByRole('button', { name: 'Cancel' }))

    expect(api.sent.size).toBe(0)
    expect(within(list).getByRole('radio', { name: 'Whisper small (English)' })).toBeChecked()
    expect(screen.queryByText(/and use it\?/)).not.toBeInTheDocument()
  })

  it('picking an installed model dismisses a proposal', async () => {
    const { user } = renderApp('/settings')
    const list = await recognition()
    await user.click(within(list).getByRole('radio', { name: 'Whisper tiny (English)' }))

    await user.click(within(list).getByRole('radio', { name: 'Whisper base' }))

    expect(screen.queryByText(/and use it\?/)).not.toBeInTheDocument()
  })

  it('downloads without using the model when asked with the button', async () => {
    const { user, api } = renderApp('/settings')
    const list = await recognition()

    await user.click(row(list, 'Whisper tiny (English)').getByRole('button', { name: /Download/ }))

    expect(api.sent.get('POST /v1/speech/models/whisper-tiny-en/download')).toEqual([
      { activate: false },
    ])
  })

  it('cancel stops the download', async () => {
    const api = fakeApi()
    api.speechModels.models = api.speechModels.models.map((m) =>
      m.key === 'whisper-tiny-en' ? { ...m, state: 'downloading', download: null } : m,
    )
    const { user } = renderApp('/settings', api)
    const list = await recognition()
    expect(
      within(list).getByRole('progressbar', { name: 'Downloading Whisper tiny (English)' }),
    ).not.toHaveAttribute('aria-valuenow')

    await user.click(row(list, 'Whisper tiny (English)').getByRole('button', { name: 'Cancel' }))

    expect(api.sent.has('DELETE /v1/speech/models/whisper-tiny-en/download')).toBe(true)
    expect(
      await row(list, 'Whisper tiny (English)').findByRole('button', { name: /Download/ }),
    ).toBeInTheDocument()
  })

  it('uninstall asks first', async () => {
    const { user, api } = renderApp('/settings')
    const list = await recognition()
    expect(
      row(list, 'Whisper small (English)').queryByRole('button', { name: 'Uninstall' }),
    ).not.toBeInTheDocument()

    const base = row(list, 'Whisper base')
    await user.click(base.getByRole('button', { name: 'Uninstall' }))
    expect(base.getByText('Remove 145 MB?')).toBeInTheDocument()
    await user.click(base.getByRole('button', { name: 'Keep' }))
    expect(base.queryByText('Remove 145 MB?')).not.toBeInTheDocument()
    expect(api.sent.has('DELETE /v1/speech/models/whisper-base')).toBe(false)

    await user.click(base.getByRole('button', { name: 'Uninstall' }))
    await user.click(base.getByRole('button', { name: 'Remove' }))

    expect(api.sent.has('DELETE /v1/speech/models/whisper-base')).toBe(true)
    expect(await base.findByRole('button', { name: /Download/ })).toBeInTheDocument()
  })

  it('uses an installed model at once, from the row or its button', async () => {
    const { user, api } = renderApp('/settings')
    const list = await recognition()

    await user.click(row(list, 'Whisper base').getByRole('button', { name: 'Use' }))

    await waitFor(() => {
      expect(row(list, 'Whisper base').getByText('In use')).toBeInTheDocument()
    })
    expect(api.sent.get('PUT /v1/speech/settings')?.at(-1)).toMatchObject({
      stt_model: 'Systran/faster-whisper-base',
      tts_voice: 'af_heart',
    })
    await user.click(within(list).getByRole('radio', { name: 'Whisper small (English)' }))
    await waitFor(() => {
      expect(row(list, 'Whisper small (English)').getByText('In use')).toBeInTheDocument()
    })
  })

  it('shows no size for a configured model the catalogue does not know', async () => {
    const api = fakeApi()
    api.speechModels.models = api.speechModels.models.map((m) =>
      m.key === 'whisper-tiny-en'
        ? { ...m, label: 'acme/whisper-custom.en', approx_mb: 0, from_configuration: true }
        : m,
    )
    const { user } = renderApp('/settings', api)
    const list = await recognition()
    const custom = row(list, 'acme/whisper-custom.en')

    expect(custom.getByText('English only')).toBeInTheDocument()
    expect(custom.getByRole('button', { name: 'Download' })).toBeInTheDocument()
    await user.click(within(list).getByRole('radio', { name: 'acme/whisper-custom.en' }))
    expect(custom.getByText('Download and use it?')).toBeInTheDocument()
    expect(custom.queryByText(/0 MB/)).not.toBeInTheDocument()
  })

  it('is read-only when the server cannot manage models', async () => {
    const api = fakeApi()
    api.speechModels.recognition_manageable = false
    renderApp('/settings', api)
    const list = await recognition()

    expect(screen.queryAllByRole('button', { name: /Download|Uninstall/ })).toHaveLength(1)
    expect(within(list).queryByRole('button', { name: /Download|Uninstall/ })).toBeNull()
    expect(within(list).getByRole('radio', { name: 'Whisper tiny (English)' })).toBeDisabled()
    expect(within(list).getByRole('radio', { name: 'Whisper base' })).toBeEnabled()
    expect(screen.getByText(/cannot be installed or removed from here/)).toBeInTheDocument()
  })

  it('shows the last download error and the models in use meanwhile', async () => {
    const api = fakeApi()
    api.speechModels.last_error = 'Download of Whisper tiny failed: disk full'
    api.speechSettings.missing = ['recognition', 'voice']
    renderApp('/settings', api)

    expect(await screen.findByText(/disk full/)).toBeInTheDocument()
    expect(
      screen.getByText(
        'Your saved speech recognition model is not installed: Whisper small (English) is used meanwhile.',
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        "Your saved tutor's voice model is not installed: Kokoro is used meanwhile.",
      ),
    ).toBeInTheDocument()
  })

  it('shows a refused action', async () => {
    const { user } = renderApp('/settings', fakeApi())
    const list = await recognition()
    const fail = vi.fn(() =>
      Response.json({ detail: 'Another download is running.' }, { status: 409 }),
    )
    const original = globalThis.fetch
    vi.stubGlobal('fetch', (request: Request) =>
      request.method === 'POST' ? Promise.resolve(fail()) : original(request),
    )

    await user.click(within(list).getByRole('radio', { name: 'Whisper tiny (English)' }))
    await user.click(row(list, 'Whisper tiny (English)').getByRole('button', { name: 'Download' }))

    expect(await screen.findByText('Another download is running.')).toBeInTheDocument()
  })

  it('reports settings it cannot load', async () => {
    renderApp('/settings', fakeApi({ speechSettings: failure(500, 'no settings') }))

    expect(await screen.findByText('no settings')).toBeInTheDocument()
  })

  it('shows a placeholder while loading', async () => {
    renderApp('/settings', fakeApi({ speechModels: () => new Promise(() => undefined) }))

    expect(await screen.findByLabelText('Loading voice settings')).toBeInTheDocument()
  })
})

describe('Longest turn', () => {
  it('saves and explains the cost', async () => {
    const api = fakeApi()
    measured(api, 120)
    const { user } = renderApp('/settings', api)
    const turn = await screen.findByRole('radiogroup', { name: 'Longest turn' })
    expect(within(turn).getByRole('radio', { name: '2 min' })).toBeChecked()

    await user.click(within(turn).getByRole('radio', { name: '3 min' }))

    expect(await screen.findByText('Saved')).toBeInTheDocument()
    expect(api.sent.get('PUT /v1/speech/settings')?.at(-1)).toMatchObject({ max_turn_s: 180 })
    expect(
      screen.getByText(
        /With Whisper small \(English\), 3 min of speech take about 22 s to transcribe here\./,
      ),
    ).toBeInTheDocument()
    expect(screen.getByText(/starts answering only after the whole turn/)).toBeInTheDocument()

    await user.click(within(turn).getByRole('radio', { name: '1 min' }))
    await waitFor(() => {
      expect(screen.queryByText(/starts answering only after/)).not.toBeInTheDocument()
    })
  })

  it('asks for a few turns when there is no measurement', async () => {
    renderApp('/settings')

    expect(
      await screen.findByText(
        /Talk a few voice turns and an estimate of the transcription time appears here\./,
      ),
    ).toBeInTheDocument()
  })

  it('shows a length outside the options in seconds', async () => {
    const api = fakeApi()
    api.speechSettings.max_turn_s = 45
    measured(api, 100)
    renderApp('/settings', api)

    expect(await screen.findByText(/45 s of speech take about 5 s/)).toBeInTheDocument()
  })

  it('shows a refused save', async () => {
    const api = fakeApi()
    const { user } = renderApp('/settings', api)
    const turn = await screen.findByRole('radiogroup', { name: 'Longest turn' })
    vi.stubGlobal('fetch', () => Promise.resolve(failure(422, 'Too long')()))

    await user.click(within(turn).getByRole('radio', { name: '5 min' }))

    expect(await screen.findByText('Too long')).toBeInTheDocument()
  })
})

describe('Tutor voice', () => {
  it('groups voices and previews them at the chosen speed', async () => {
    const { user, api } = renderApp('/settings')
    const american = await screen.findByRole('region', { name: 'American' })
    const british = screen.getByRole('region', { name: 'British' })

    expect(within(american).getByRole('group', { name: 'American Female' })).toBeInTheDocument()
    expect(within(american).getByRole('group', { name: 'American Male' })).toBeInTheDocument()
    expect(within(british).getByRole('group', { name: 'British Female' })).toBeInTheDocument()
    expect(within(british).getByRole('group', { name: 'British Male' })).toBeInTheDocument()
    expect(within(american).getByRole('radio', { name: 'Heart' })).toBeChecked()

    await user.click(within(british).getByRole('button', { name: 'Preview Emma' }))

    await waitFor(() => {
      expect(played).toEqual(['blob:preview'])
    })
    expect(api.sent.get('POST /v1/speech/preview')).toEqual([
      { model: 'speaches-ai/Kokoro-82M-v1.0-ONNX', voice: 'bf_emma', speed: 0.95 },
    ])
    FakeAudio.ended?.()
    // eslint-disable-next-line @typescript-eslint/unbound-method
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:preview')

    await user.click(within(british).getByRole('radio', { name: 'George' }))
    await waitFor(() => {
      expect(api.sent.get('PUT /v1/speech/settings')?.at(-1)).toMatchObject({
        tts_voice: 'bm_george',
      })
    })
  })

  it('speed saves within 0.7 and 1.3', async () => {
    const { user, api } = renderApp('/settings')
    const speed = await screen.findByRole('radiogroup', { name: 'Speed' })
    expect(within(speed).getByRole('radio', { name: '0.95×' })).toBeChecked()

    await user.click(within(speed).getByRole('radio', { name: '1.3×' }))
    await waitFor(() => {
      expect(within(speed).getByRole('radio', { name: '1.3×' })).toBeChecked()
    })
    await user.click(within(speed).getByRole('radio', { name: '0.7×' }))
    await waitFor(() => {
      expect(within(speed).getByRole('radio', { name: '0.7×' })).toBeChecked()
    })

    const speeds = (api.sent.get('PUT /v1/speech/settings') as { tts_speed: number }[]).map(
      (body) => body.tts_speed,
    )
    expect(speeds).toEqual([1.3, 0.7])
  })

  it('previews with the speed just chosen', async () => {
    const { user, api } = renderApp('/settings')
    const speed = await screen.findByRole('radiogroup', { name: 'Speed' })
    await user.click(within(speed).getByRole('radio', { name: '1.2×' }))
    await waitFor(() => {
      expect(within(speed).getByRole('radio', { name: '1.2×' })).toBeChecked()
    })

    await user.click(screen.getByRole('button', { name: 'Preview Heart' }))

    await waitFor(() => {
      expect(api.sent.get('POST /v1/speech/preview')?.at(-1)).toMatchObject({ speed: 1.2 })
    })
  })

  it('says when a preview fails', async () => {
    const { user } = renderApp('/settings', fakeApi({ preview: failure(502, 'Speaches is down') }))

    await user.click(await screen.findByRole('button', { name: 'Preview Heart' }))

    expect(await screen.findByText('Speaches is down')).toBeInTheDocument()
  })

  it('switching the voice model keeps the voice it also has, else takes its first', async () => {
    const api = fakeApi()
    api.speechModels.models = api.speechModels.models.map((m) =>
      m.key === 'piper-lessac' ? { ...m, state: 'installed' } : m,
    )
    const { user } = renderApp('/settings', api)
    const list = await voiceModels()

    await user.click(within(list).getByRole('radio', { name: 'Piper Lessac' }))
    await waitFor(() => {
      expect(api.sent.get('PUT /v1/speech/settings')?.at(-1)).toMatchObject({
        tts_model: 'speaches-ai/piper-en_US-lessac-medium',
        tts_voice: 'af_heart',
      })
    })

    api.voices = [{ id: 'amy', name: 'Amy', accent: null, gender: null }]
    await user.click(within(list).getByRole('radio', { name: 'Kokoro' }))
    await waitFor(() => {
      expect(api.sent.get('PUT /v1/speech/settings')?.at(-1)).toMatchObject({
        tts_model: 'speaches-ai/Kokoro-82M-v1.0-ONNX',
      })
    })
  })

  it('takes the first voice when the new model does not have the current one', async () => {
    const api = fakeApi()
    api.speechSettings.tts_voice = 'old'
    api.speechModels.models = api.speechModels.models.map((m) =>
      m.key === 'piper-lessac' ? { ...m, state: 'installed' } : m,
    )
    const { user } = renderApp('/settings', api)
    const list = await voiceModels()

    await user.click(within(list).getByRole('radio', { name: 'Piper Lessac' }))

    await waitFor(() => {
      expect(api.sent.get('PUT /v1/speech/settings')?.at(-1)).toMatchObject({
        tts_voice: 'af_heart',
      })
    })
  })

  it('keeps the voice when the new model lists none', async () => {
    const api = fakeApi()
    api.speechModels.models = api.speechModels.models.map((m) =>
      m.key === 'piper-lessac' ? { ...m, state: 'installed' } : m,
    )
    const { user } = renderApp('/settings', api)
    const list = await voiceModels()
    api.voices = []

    await user.click(within(list).getByRole('radio', { name: 'Piper Lessac' }))

    await waitFor(() => {
      expect(api.sent.get('PUT /v1/speech/settings')?.at(-1)).toMatchObject({
        tts_voice: 'af_heart',
      })
    })
  })

  it('says when a model lists no voices, and puts ungrouped ones under Other', async () => {
    const api = fakeApi()
    api.voices = [{ id: 'amy', name: 'Amy', accent: null, gender: null }]
    const first = renderApp('/settings', api)
    expect(await screen.findByRole('region', { name: 'Other' })).toBeInTheDocument()
    first.unmount()

    api.voices = []
    renderApp('/settings', api)
    expect(
      await screen.findByText('This voice model does not list its voices.'),
    ).toBeInTheDocument()
  })

  it('falls back when voices cannot be listed', async () => {
    const api = fakeApi()
    api.speechModels.models = api.speechModels.models.map((m) =>
      m.key === 'piper-lessac' ? { ...m, state: 'installed' } : m,
    )
    const { user } = renderApp('/settings', api)
    const list = await voiceModels()
    vi.stubGlobal('fetch', async (request: Request) =>
      new URL(request.url).pathname === '/v1/speech/voices'
        ? Response.json({ detail: 'down' }, { status: 502 })
        : api.fetch(request),
    )

    await user.click(within(list).getByRole('radio', { name: 'Piper Lessac' }))

    await waitFor(() => {
      expect(api.sent.get('PUT /v1/speech/settings')?.at(-1)).toMatchObject({
        tts_model: 'speaches-ai/piper-en_US-lessac-medium',
        tts_voice: 'af_heart',
      })
    })
  })
})

describe('Saving', () => {
  it('re-checks readiness after a save', async () => {
    const { user, api } = renderApp('/settings')
    const speed = await screen.findByRole('radiogroup', { name: 'Speed' })
    await screen.findAllByLabelText('Ready')
    const checked = statusChecks(api)

    await user.click(within(speed).getByRole('radio', { name: '1.2×' }))

    await waitFor(() => {
      expect(statusChecks(api)).toBeGreaterThan(checked)
    })
  })

  it('locks the model lists while a save runs', async () => {
    const api = fakeApi()
    const { user } = renderApp('/settings', api)
    const speed = await screen.findByRole('radiogroup', { name: 'Speed' })
    const list = await recognition()
    const release = holding(api, (request) => request.method === 'PUT')

    await user.click(within(speed).getByRole('radio', { name: '1.2×' }))

    await waitFor(() => {
      expect(within(list).getByRole('radio', { name: 'Whisper base' })).toBeDisabled()
    })
    expect(row(list, 'Whisper base').getByRole('button', { name: 'Use' })).toBeDisabled()
    release()
    await waitFor(() => {
      expect(within(list).getByRole('radio', { name: 'Whisper base' })).toBeEnabled()
    })
  })

  it('a voice model chosen before a speed change keeps the new speed', async () => {
    const api = fakeApi()
    api.speechModels.models = api.speechModels.models.map((m) =>
      m.key === 'piper-lessac' ? { ...m, state: 'installed' } : m,
    )
    const { user } = renderApp('/settings', api)
    const list = await voiceModels()
    const speed = screen.getByRole('radiogroup', { name: 'Speed' })
    const release = holding(
      api,
      (request) => new URL(request.url).searchParams.get('model') === LESSAC,
    )

    await user.click(within(list).getByRole('radio', { name: 'Piper Lessac' })) // asks its voices
    await user.click(within(speed).getByRole('radio', { name: '1.2×' }))
    expect(await screen.findByText('Saved')).toBeInTheDocument()
    release()

    await waitFor(() => {
      expect(api.sent.get('PUT /v1/speech/settings')?.at(-1)).toMatchObject({
        tts_model: LESSAC,
        tts_speed: 1.2,
      })
    })
  })
})

describe('Voice section', () => {
  it('says changes apply from the next conversation, below the readiness rows', async () => {
    renderApp('/settings')

    expect(await screen.findByText('Changes apply from your next conversation.')).toBeVisible()
    const ready = screen.getAllByLabelText('Ready')[0]
    const list = await recognition()
    expect(ready?.compareDocumentPosition(list) === Node.DOCUMENT_POSITION_FOLLOWING).toBe(true)
  })
})

describe('playPreview', () => {
  it('requests the sample as audio and plays it', async () => {
    const api = fakeApi()
    renderApp('/settings', api)

    await playPreview({ model: 'm', voice: 'v', speed: 1 })

    expect(played).toEqual(['blob:preview'])
  })
})

const GPU_SMALL = 'ggerganov/whisper.cpp/ggml-small.en-q8_0.bin'
const GPU_BASE = 'ggerganov/whisper.cpp/ggml-base.en-q5_1.bin'

function gpuRunning(api: FakeApi, running = true) {
  api.speechModels.engines = api.speechModels.engines.map((state) =>
    state.engine === 'whispercpp' ? { ...state, running } : state,
  )
}

describe('Speech recognition engine', () => {
  it('switching the engine saves it and leaves the other fields as they were', async () => {
    const api = fakeApi()
    gpuRunning(api)
    const { user } = renderApp('/settings', api)
    const engine = await screen.findByRole('radiogroup', { name: 'Speech recognition engine' })

    await user.click(within(engine).getByRole('radio', { name: 'whisper.cpp · GPU' }))

    expect(await screen.findByText('Saved')).toBeInTheDocument()
    expect(api.sent.get('PUT /v1/speech/settings')?.at(-1)).toEqual({
      stt_model: 'Systran/faster-distil-whisper-small.en',
      stt_engine: 'whispercpp',
      stt_gpu_model: GPU_SMALL,
      tts_model: 'speaches-ai/Kokoro-82M-v1.0-ONNX',
      tts_voice: 'af_heart',
      tts_speed: 0.95,
      max_turn_s: 120,
    })
  })

  it('cannot switch to a stopped engine', async () => {
    renderApp('/settings')
    const engine = await screen.findByRole('radiogroup', { name: 'Speech recognition engine' })

    expect(within(engine).getByRole('radio', { name: 'whisper.cpp · GPU' })).toBeDisabled()
  })

  it('lists only the GPU models under whisper.cpp, and Use keeps the CPU model', async () => {
    const api = fakeApi()
    gpuRunning(api)
    api.speechSettings.stt_engine = 'whispercpp'
    const { user } = renderApp('/settings', api)
    const list = await recognition()

    expect(within(list).queryByRole('radio', { name: 'Whisper base' })).not.toBeInTheDocument()
    expect(row(list, 'whisper.cpp small (English, q8)').getByText('In use')).toBeInTheDocument()

    await user.click(
      row(list, 'whisper.cpp base (English, q5)').getByRole('button', { name: 'Use' }),
    )

    expect(await screen.findByText('Saved')).toBeInTheDocument()
    expect(api.sent.get('PUT /v1/speech/settings')?.at(-1)).toMatchObject({
      stt_engine: 'whispercpp',
      stt_gpu_model: GPU_BASE,
      stt_model: 'Systran/faster-distil-whisper-small.en',
    })
    expect(row(list, 'whisper.cpp base (English, q5)').getByText('In use')).toBeInTheDocument()
  })

  it('says Speaches is used meanwhile when the saved engine is stopped', async () => {
    const api = fakeApi()
    api.speechSettings.stt_engine = 'whispercpp'
    renderApp('/settings', api)

    expect(
      await screen.findByText('whisper.cpp (GPU) is not running: Speaches is used meanwhile.'),
    ).toBeInTheDocument()
  })

  it('does not say it while the engine runs', async () => {
    const api = fakeApi()
    gpuRunning(api)
    api.speechSettings.stt_engine = 'whispercpp'
    renderApp('/settings', api)
    await recognition()

    expect(screen.queryByText(/is not running/)).not.toBeInTheDocument()
  })

  it('estimates the turn with the model of the engine in use', async () => {
    const api = fakeApi()
    gpuRunning(api)
    api.speechSettings.stt_engine = 'whispercpp'
    api.speechModels.models = api.speechModels.models.map((m) =>
      m.key === 'ggml-small-en-q8' ? { ...m, ms_per_audio_s: 60 } : m,
    )
    measured(api, 500)
    renderApp('/settings', api)

    expect(
      await screen.findByText(
        /With whisper\.cpp small \(English, q8\), 2 min of speech take about 7 s/,
      ),
    ).toBeInTheDocument()
  })

  it('names the default of the engine in use when the saved model is missing', async () => {
    const api = fakeApi()
    gpuRunning(api)
    api.speechSettings.stt_engine = 'whispercpp'
    api.speechSettings.missing = ['recognition']
    renderApp('/settings', api)

    expect(
      await screen.findByText(
        'Your saved speech recognition model is not installed: whisper.cpp small (English, q8) is used meanwhile.',
      ),
    ).toBeInTheDocument()
  })

  it('names the Speaches default when the saved GPU engine is stopped', async () => {
    const api = fakeApi()
    api.speechSettings.stt_engine = 'whispercpp'
    api.speechSettings.missing = ['recognition']
    renderApp('/settings', api)

    expect(
      await screen.findByText(
        'Your saved speech recognition model is not installed: Whisper small (English) is used meanwhile.',
      ),
    ).toBeInTheDocument()
  })

  it('shows why a switch was refused', async () => {
    const api = fakeApi()
    gpuRunning(api)
    const { user } = renderApp('/settings', api)
    const engine = await screen.findByRole('radiogroup', { name: 'Speech recognition engine' })
    const original = globalThis.fetch
    vi.stubGlobal('fetch', (request: Request) =>
      request.method === 'PUT'
        ? Promise.resolve(failure(409, 'whisper.cpp (GPU) is not running.')())
        : original(request),
    )

    await user.click(within(engine).getByRole('radio', { name: 'whisper.cpp · GPU' }))

    expect(await screen.findByText('whisper.cpp (GPU) is not running.')).toBeInTheDocument()
  })
})

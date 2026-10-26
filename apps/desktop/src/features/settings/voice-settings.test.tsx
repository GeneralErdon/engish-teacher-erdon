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

    await user.click(within(list).getByRole('radio', { name: 'Whisper tiny (English)' }))

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

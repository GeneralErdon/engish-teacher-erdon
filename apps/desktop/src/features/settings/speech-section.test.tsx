import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { fakeApi, pending, type FakeApi } from '@/test/fake-api'
import { renderApp } from '@/test/render-app'

const STT = 'Systran/faster-distil-whisper-small.en'
const TTS = 'speaches-ai/Kokoro-82M-v1.0-ONNX'
const download = (model: string) =>
  `SPEACHES_BASE_URL=http://localhost:8000 uvx speaches-cli model download ${model}`

function section() {
  const heading = screen.getByRole('heading', { name: 'Voice' })
  const card = heading.closest('[data-slot="card"]')
  if (!(card instanceof HTMLElement)) throw new Error('no card')
  return within(card)
}

/** The "One-time setup" alert: the engine choice below it shows start commands too. */
function setup() {
  const alert = section().getByText('One-time setup').closest('[data-slot="alert"]')
  if (!(alert instanceof HTMLElement)) throw new Error('no setup alert')
  return within(alert)
}

function notReady(api: FakeApi, part: 'recognition' | 'synthesis', reachable = true) {
  const detail = reachable ? null : 'Could not connect to http://localhost:8000/v1.'
  api.speech = {
    ...api.speech,
    [part]: { ...api.speech[part], reachable, model_ready: false, detail },
  }
}

describe('Voice settings', () => {
  it('says when both are ready, with the one server they share', async () => {
    renderApp('/settings')

    expect(await screen.findByText(STT)).toBeInTheDocument()
    expect(section().getByText(TTS)).toBeInTheDocument()
    expect(section().getAllByLabelText('Ready')).toHaveLength(2)
    expect(section().getAllByText('http://localhost:8000/v1')).toHaveLength(1)
    expect(section().queryByText('One-time setup')).not.toBeInTheDocument()
  })

  it('gives one command when Speaches is not running: it also downloads the models', async () => {
    const api = fakeApi()
    notReady(api, 'recognition', false)
    notReady(api, 'synthesis', false)
    renderApp('/settings', api)

    expect(await screen.findByText('One-time setup')).toBeInTheDocument()
    expect(section().getAllByText('Could not connect to http://localhost:8000/v1.')).toHaveLength(2)
    expect(setup().getByText('just voice')).toBeInTheDocument()
    expect(setup().getByText(/first start downloads the models/)).toBeInTheDocument()
    expect(setup().queryByText(/speaches-cli/)).not.toBeInTheDocument()
  })

  it('only asks for the missing model when the server runs, and checks again', async () => {
    const api = fakeApi()
    notReady(api, 'synthesis')
    const { user } = renderApp('/settings', api)

    expect(await screen.findByText('Not ready.')).toBeInTheDocument()
    expect(setup().getByText(/downloads what is missing/)).toBeInTheDocument()
    expect(setup().getByText('just voice')).toBeInTheDocument()
    expect(setup().getByText(download(TTS))).toBeInTheDocument()
    expect(setup().queryByText(download(STT))).not.toBeInTheDocument()

    api.speech = fakeApi().speech
    await user.click(section().getByRole('button', { name: /check again/i }))

    expect(await screen.findByText(TTS)).toBeInTheDocument()
  })

  it('names whisper.cpp and its start command when it transcribes', async () => {
    const api = fakeApi()
    api.speech.recognition_engine = 'whispercpp'
    notReady(api, 'recognition', false)
    renderApp('/settings', api)

    expect(await screen.findByText('Speech recognition · whisper.cpp (GPU)')).toBeInTheDocument()
    expect(
      setup().getByText('Start Speaches and the GPU speech recognition server:'),
    ).toBeInTheDocument()
    expect(setup().getByText('just voice gpu')).toBeInTheDocument()
    expect(setup().queryByText('just voice')).not.toBeInTheDocument()
    expect(setup().queryByText(/700 MB/)).not.toBeInTheDocument()
    expect(setup().queryByText(/speaches-cli/)).not.toBeInTheDocument()
  })

  it('says how to restart whisper.cpp when it answers but holds no model', async () => {
    const api = fakeApi()
    api.speech.recognition_engine = 'whispercpp'
    notReady(api, 'recognition')
    renderApp('/settings', api)

    expect(
      await screen.findByText(
        'The GPU speech recognition server is loading a model, or needs a restart:',
      ),
    ).toBeInTheDocument()
    expect(setup().getByText('docker compose restart stt-gpu')).toBeInTheDocument()
    // speaches-cli cannot download whisper.cpp's GGML files.
    expect(setup().queryByText(/speaches-cli/)).not.toBeInTheDocument()
    expect(setup().queryByText(/downloads what is missing/)).not.toBeInTheDocument()
  })

  it('still offers the Speaches download for the voice while whisper.cpp transcribes', async () => {
    const api = fakeApi()
    api.speech.recognition_engine = 'whispercpp'
    notReady(api, 'synthesis')
    renderApp('/settings', api)

    expect(await screen.findByText(/downloads what is missing/)).toBeInTheDocument()
    expect(setup().getByText('just voice gpu')).toBeInTheDocument()
    expect(setup().getByText(download(TTS))).toBeInTheDocument()
    expect(setup().queryByText(/loading a model/)).not.toBeInTheDocument()
  })

  it('lists each server when they differ', async () => {
    const api = fakeApi()
    api.speech.synthesis.base_url = 'http://localhost:8880/v1'
    renderApp('/settings', api)

    expect(await screen.findByText('http://localhost:8880/v1')).toBeInTheDocument()
    expect(section().getByText('http://localhost:8000/v1')).toBeInTheDocument()
  })

  it('reports a status it cannot load', async () => {
    renderApp(
      '/settings',
      fakeApi({ speech: () => Response.json({ detail: 'boom' }, { status: 500 }) }),
    )
    expect(await screen.findByText('boom')).toBeInTheDocument()
  })

  it('shows a placeholder while checking', async () => {
    renderApp('/settings', fakeApi({ speech: pending }))
    await screen.findByRole('heading', { name: 'Voice' })

    expect(section().getByLabelText('Loading')).toBeInTheDocument()
  })
})

describe('Voice on Home', () => {
  it('is ready, half set up, or not set up', async () => {
    const api = fakeApi()
    const first = renderApp('/', api)
    expect(
      await screen.findByText('Press the mic in Practice and speak: your tutor answers out loud.'),
    ).toBeInTheDocument()
    first.unmount()

    notReady(api, 'synthesis')
    const second = renderApp('/', api)
    expect(await screen.findByText('Half set up')).toBeInTheDocument()
    expect(screen.getByText(/its voice needs a one-time setup/)).toBeInTheDocument()
    second.unmount()

    notReady(api, 'recognition')
    renderApp('/', api)
    expect(await screen.findByText('Not set up')).toBeInTheDocument()
    expect(screen.getByText(/Speech runs on your machine/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Set it up' })).toBeInTheDocument()
  })
})

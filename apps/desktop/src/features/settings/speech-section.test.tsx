import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { fakeApi, pending } from '@/test/fake-api'
import { renderApp } from '@/test/render-app'

const MODEL = 'Systran/faster-distil-whisper-small.en'

function section() {
  const heading = screen.getByRole('heading', { name: 'Speech recognition' })
  const card = heading.closest('[data-slot="card"]')
  if (!(card instanceof HTMLElement)) throw new Error('no card')
  return within(card)
}

describe('Speech recognition settings', () => {
  it('says when it is ready', async () => {
    renderApp('/settings')

    expect(await screen.findByText(`Ready: ${MODEL}`)).toBeInTheDocument()
    expect(section().getByText('http://localhost:8000/v1')).toBeInTheDocument()
  })

  it('gives the two setup commands when Speaches is not running', async () => {
    const api = fakeApi()
    api.speech = {
      ...api.speech,
      reachable: false,
      model_ready: false,
      detail: 'Could not connect to http://localhost:8000/v1.',
    }
    renderApp('/settings', api)

    expect(
      await screen.findByText('Could not connect to http://localhost:8000/v1.'),
    ).toBeInTheDocument()
    expect(section().getByText('docker compose --profile cpu up -d stt-cpu')).toBeInTheDocument()
    expect(
      section().getByText(
        `SPEACHES_BASE_URL=http://localhost:8000 uvx speaches-cli model download ${MODEL}`,
      ),
    ).toBeInTheDocument()
  })

  it('only asks for the download when the server runs, and checks again on demand', async () => {
    const api = fakeApi()
    api.speech = { ...api.speech, model_ready: false, detail: null }
    const { user } = renderApp('/settings', api)

    expect(await screen.findByText('Speech recognition is not ready.')).toBeInTheDocument()
    expect(section().queryByText(/docker compose/)).not.toBeInTheDocument()

    api.speech = { ...api.speech, model_ready: true }
    await user.click(section().getByRole('button', { name: /check again/i }))

    expect(await screen.findByText(`Ready: ${MODEL}`)).toBeInTheDocument()
  })

  it('reports a status it cannot load, and shows a placeholder meanwhile', async () => {
    renderApp(
      '/settings',
      fakeApi({ speech: () => Response.json({ detail: 'boom' }, { status: 500 }) }),
    )
    expect(await screen.findByText('boom')).toBeInTheDocument()
  })

  it('shows a placeholder while checking', async () => {
    renderApp('/settings', fakeApi({ speech: pending }))
    await screen.findByRole('heading', { name: 'Speech recognition' })

    expect(section().getByLabelText('Loading')).toBeInTheDocument()
  })
})

describe('Voice on Home', () => {
  it('is ready, or points to the setup', async () => {
    const api = fakeApi()
    const { unmount } = renderApp('/', api)
    expect(await screen.findByText('Press the mic in Practice and speak.')).toBeInTheDocument()
    unmount()

    api.speech = { ...api.speech, model_ready: false }
    renderApp('/', api)
    expect(await screen.findByText('Not set up')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Set it up' })).toBeInTheDocument()
  })
})

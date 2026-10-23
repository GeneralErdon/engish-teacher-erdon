import { act, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { fakeApi, pending, unreachable } from '@/test/fake-api'
import { renderApp } from '@/test/render-app'

import { App } from './App'

describe('Home', () => {
  it('welcomes the learner and shows what is running', async () => {
    renderApp('/')

    expect(
      await screen.findByRole('heading', { name: /speak english with confidence/i }),
    ).toBeInTheDocument()
    expect(await screen.findByText('Version 0.1.0 at')).toBeInTheDocument()
    expect(await screen.findByText('OpenAI-compatible')).toBeInTheDocument()
    expect(screen.getByText('gemma-3-4b-it-q4')).toBeInTheDocument()
    expect(screen.getByText('From .env')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /start a conversation/i })).toHaveAttribute(
      'href',
      '/practice',
    )
    expect(screen.getAllByRole('status')[0]).toHaveTextContent('API online · v0.1.0')
  })

  it('marks the steps that are done', async () => {
    const api = fakeApi()
    api.settings = { ...api.settings, source: 'saved' }
    renderApp('/', api)

    expect(await screen.findByText('Saved in the app')).toBeInTheDocument()
    const steps = within(screen.getByRole('list', { name: 'Getting started' }))
    expect(steps.getAllByLabelText('Done')).toHaveLength(2)
  })

  it('explains how to start the backend when it is down, and retries', async () => {
    let checks = 0
    const api = fakeApi({ health: () => (++checks === 1 ? unreachable() : pending()) })
    const { user } = renderApp('/', api)

    expect(await screen.findByText('Offline')).toBeInTheDocument()
    expect(screen.getAllByText('Waiting for the backend.')).toHaveLength(2) // model and voice cards
    expect(screen.getAllByRole('status')[0]).toHaveTextContent('API offline')

    await user.click(screen.getByRole('button', { name: 'Retry' }))

    expect(checks).toBe(2)
    expect(screen.getAllByRole('status')[0]).toHaveTextContent('Checking the API…')
  })

  it('notices when the backend goes down, and spins while retrying', async () => {
    let checks = 0
    const health = () => Response.json({ status: 'ok', service: 'api', version: '0.1.0' })
    const api = fakeApi({
      health: () => [health, unreachable][++checks - 1]?.() ?? pending(),
    })
    const { user, queryClient } = renderApp('/', api)
    expect(await screen.findByText('Online')).toBeInTheDocument()

    await act(() => queryClient.refetchQueries({ queryKey: ['get', '/healthz'] }))
    expect(await screen.findByText('Offline')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Retry' }))

    expect(screen.getByRole('button', { name: 'Retry' })).toBeDisabled()
  })

  it('shows placeholders while the backend answers', async () => {
    renderApp('/', fakeApi({ health: pending }))

    expect((await screen.findAllByRole('status'))[0]).toHaveTextContent('Checking the API…')
  })
})

describe('Navigation', () => {
  it('moves between Home and Settings, highlighting the current page', async () => {
    const { user } = renderApp('/')
    const [sidebar] = await screen.findAllByRole('navigation', { name: 'Main' })
    if (!sidebar) throw new Error('no navigation')

    await user.click(within(sidebar).getByRole('link', { name: 'Settings' }))

    expect(await screen.findByRole('heading', { name: 'Settings', level: 1 })).toBeInTheDocument()
    expect(within(sidebar).getByRole('link', { name: 'Settings' })).toHaveAttribute(
      'data-status',
      'active',
    )

    await user.click(within(sidebar).getByRole('link', { name: 'Home' }))

    expect(await screen.findByRole('heading', { name: /speak english/i })).toBeInTheDocument()
  })

  it('has a tab bar for small screens', async () => {
    renderApp('/')

    const tabs = (await screen.findAllByRole('navigation', { name: 'Main' }))[1]
    expect(tabs).toBeDefined()
    expect(within(tabs as HTMLElement).getAllByRole('link')).toHaveLength(3)
  })

  it('says so when a page does not exist', async () => {
    const { user } = renderApp('/nowhere')

    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
    await user.click(screen.getByRole('link', { name: 'Back home' }))
    expect(await screen.findByRole('heading', { name: /speak english/i })).toBeInTheDocument()
  })
})

describe('Theme', () => {
  it('switches between light and dark from the top bar', async () => {
    const { user } = renderApp('/')
    const [toggle] = await screen.findAllByRole('button', { name: 'Switch to dark theme' })

    await user.click(toggle as HTMLElement)

    expect(document.documentElement).toHaveClass('dark')
    expect(screen.getAllByRole('button', { name: 'Switch to light theme' })).not.toHaveLength(0)
  })
})

describe('App defaults', () => {
  it('creates its own router and cache', async () => {
    vi.stubGlobal('fetch', fakeApi().fetch)
    window.location.hash = '#/'

    await act(async () => {
      render(<App />)
      await Promise.resolve()
    })

    expect(await screen.findByRole('heading', { name: /speak english/i })).toBeInTheDocument()
  })
})

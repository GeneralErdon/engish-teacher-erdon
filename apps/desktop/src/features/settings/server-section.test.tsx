import { isTauri } from '@tauri-apps/api/core'
import { screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { reloadApp, saveServer, savedServer } from '@/lib/platform'
import { fakeApi } from '@/test/fake-api'
import { renderApp } from '@/test/render-app'

vi.mock('@tauri-apps/api/core', () => ({ isTauri: vi.fn(() => false) }))
vi.mock('@/lib/platform', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/platform')>()),
  reloadApp: vi.fn(),
}))

async function backendSection(api = fakeApi()) {
  const view = renderApp('/settings', api)
  const heading = await screen.findByRole('heading', { name: 'Backend' })
  const card = heading.closest('[data-slot="card"]')
  if (!(card instanceof HTMLElement)) throw new Error('no card')
  return { ...view, section: within(card) }
}

function asApp() {
  vi.mocked(isTauri).mockReturnValue(true)
}

describe('Backend settings', () => {
  it('in a browser, only shows the server the page came from', async () => {
    const { section } = await backendSection()

    expect(section.getByText(window.location.origin)).toBeInTheDocument()
    expect(section.queryByLabelText('Server address')).not.toBeInTheDocument()
  })

  it('in the app, checks a server on the network, saves it and reloads', async () => {
    asApp()
    const { section, user } = await backendSection()
    expect(section.getByText('http://localhost:8080')).toBeInTheDocument()

    await user.type(section.getByLabelText('Server address'), '192.168.0.111:8080{Enter}')

    expect(savedServer()).toBe('http://192.168.0.111:8080')
    expect(reloadApp).toHaveBeenCalledOnce()
  })

  it('says what to type when the address is not one', async () => {
    asApp()
    const { section, user } = await backendSection()

    await user.type(section.getByLabelText('Server address'), 'ftp://nope{Enter}')

    expect(section.getByRole('alert')).toHaveTextContent('like 192.168.0.10:8080')
    expect(section.getByLabelText('Server address')).toHaveAttribute('aria-invalid', 'true')
    expect(reloadApp).not.toHaveBeenCalled()
  })

  it.each([
    ['an error', () => Response.json({ detail: 'no' }, { status: 503 })],
    ['nothing', () => Promise.reject(new TypeError('Failed to fetch'))],
  ])('keeps the current server when the new one answers %s', async (_, health) => {
    asApp()
    const { section, user } = await backendSection(fakeApi({ health }))

    await user.type(section.getByLabelText('Server address'), 'http://192.168.0.111:8080')
    await user.click(section.getByRole('button', { name: 'Check and use' }))

    expect(await section.findByRole('alert')).toHaveTextContent(
      'No tutor answered at http://192.168.0.111:8080',
    )
    expect(savedServer()).toBeUndefined()
    expect(section.getByRole('button', { name: 'Check and use' })).toBeEnabled()
  })

  it('goes back to this computer', async () => {
    asApp()
    saveServer('http://192.168.0.111:8080')
    const { section, user } = await backendSection()
    expect(section.getByLabelText('Server address')).toHaveValue('http://192.168.0.111:8080')

    await user.click(section.getByRole('button', { name: /this computer/i }))

    expect(savedServer()).toBeUndefined()
    expect(reloadApp).toHaveBeenCalledOnce()
  })
})

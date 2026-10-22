import { isTauri } from '@tauri-apps/api/core'
import { describe, expect, it, vi } from 'vitest'

import { type BackendContext, backendUrl, resolveBackendUrl } from './platform'

vi.mock('@tauri-apps/api/core', () => ({ isTauri: vi.fn(() => false) }))

const browserBuild: BackendContext = {
  configured: undefined,
  inTauri: false,
  dev: false,
  origin: 'https://tutor.home.lan',
}

describe('resolveBackendUrl', () => {
  it('uses its own origin when the api serves the UI', () => {
    expect(resolveBackendUrl(browserBuild)).toBe('https://tutor.home.lan')
  })

  it('talks to the local api from the desktop app and the dev server', () => {
    expect(resolveBackendUrl({ ...browserBuild, inTauri: true })).toBe('http://localhost:8080')
    expect(resolveBackendUrl({ ...browserBuild, dev: true })).toBe('http://localhost:8080')
  })

  it('lets VITE_BACKEND_URL override everything, without a trailing slash', () => {
    const ctx = { ...browserBuild, inTauri: true, configured: 'http://192.168.1.10:8080/' }

    expect(resolveBackendUrl(ctx)).toBe('http://192.168.1.10:8080')
  })
})

describe('backendUrl', () => {
  it('reads the build-time configuration and the runtime', () => {
    vi.stubEnv('VITE_BACKEND_URL', 'http://homelab:8080/')

    expect(backendUrl()).toBe('http://homelab:8080')
  })

  it('uses the local api inside the desktop app', () => {
    vi.stubEnv('DEV', false)
    vi.mocked(isTauri).mockReturnValueOnce(true)

    expect(backendUrl()).toBe('http://localhost:8080')
  })

  it("uses the page's origin in the browser build", () => {
    vi.stubEnv('DEV', false)

    expect(backendUrl()).toBe(window.location.origin)
  })
})

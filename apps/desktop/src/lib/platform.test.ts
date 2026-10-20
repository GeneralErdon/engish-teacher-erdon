import { describe, expect, it } from 'vitest'

import { type BackendContext, resolveBackendUrl } from './platform'

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

import { isTauri } from '@tauri-apps/api/core'
import { describe, expect, it, vi } from 'vitest'

import {
  type BackendContext,
  backendUrl,
  inApp,
  normalizeServer,
  resolveBackendUrl,
  saveServer,
  savedServer,
} from './platform'

vi.mock('@tauri-apps/api/core', () => ({ isTauri: vi.fn(() => false) }))

const browser: BackendContext = {
  saved: undefined,
  configured: undefined,
  inTauri: false,
  origin: 'https://tutor.home.lan',
}

describe('resolveBackendUrl', () => {
  it("uses the page's origin in a browser: the api or the dev server's proxy serves it", () => {
    expect(resolveBackendUrl(browser)).toBe('https://tutor.home.lan')
  })

  it('talks to the local api from the app', () => {
    expect(resolveBackendUrl({ ...browser, inTauri: true })).toBe('http://localhost:8080')
  })

  it('lets VITE_BACKEND_URL override the defaults, without a trailing slash', () => {
    const ctx = { ...browser, inTauri: true, configured: 'http://192.168.1.10:8080/' }

    expect(resolveBackendUrl(ctx)).toBe('http://192.168.1.10:8080')
  })

  it('puts the server saved in the app above everything', () => {
    const ctx = {
      ...browser,
      inTauri: true,
      configured: 'http://homelab:8080',
      saved: 'http://192.168.0.111:8080',
    }

    expect(resolveBackendUrl(ctx)).toBe('http://192.168.0.111:8080')
  })
})

describe('backendUrl', () => {
  it('reads the build-time configuration and the runtime', () => {
    vi.stubEnv('VITE_BACKEND_URL', 'http://homelab:8080/')

    expect(backendUrl()).toBe('http://homelab:8080')
  })

  it('uses the local api inside the app', () => {
    vi.mocked(isTauri).mockReturnValueOnce(true)

    expect(backendUrl()).toBe('http://localhost:8080')
  })

  it("uses the page's origin in a browser", () => {
    expect(backendUrl()).toBe(window.location.origin)
  })

  it('uses the server saved on this device', () => {
    saveServer('http://192.168.0.111:8080')

    expect(backendUrl()).toBe('http://192.168.0.111:8080')
    saveServer(null)
    expect(savedServer()).toBeUndefined()
  })

  it('knows when it runs as the installed app', () => {
    vi.mocked(isTauri).mockReturnValueOnce(true)

    expect(inApp()).toBe(true)
    expect(inApp()).toBe(false)
  })
})

describe('the saved server', () => {
  it('survives storage that is unavailable', () => {
    const blocked = () => {
      throw new DOMException('blocked', 'SecurityError')
    }
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(blocked)
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(blocked)

    saveServer('http://192.168.0.111:8080')

    expect(savedServer()).toBeUndefined()
  })
})

describe('normalizeServer', () => {
  it.each([
    ['192.168.0.111:8080', 'http://192.168.0.111:8080'],
    ['  http://tutor.lan:8080/  ', 'http://tutor.lan:8080'],
    ['https://tutor.example/voice/', 'https://tutor.example/voice'],
    ['HTTP://Tutor.LAN', 'http://tutor.lan'],
  ])('%s → %s', (input, url) => {
    expect(normalizeServer(input)).toBe(url)
  })

  it.each(['', '   ', 'ftp://tutor.lan', 'http://', 'not a server at all'])(
    'rejects %j',
    (input) => {
      expect(normalizeServer(input)).toBeUndefined()
    },
  )
})

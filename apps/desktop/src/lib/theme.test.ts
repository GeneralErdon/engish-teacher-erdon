import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { setPrefersDark } from '@/test/match-media'

// The theme module caches its state: load a fresh copy for every test.
async function loadTheme() {
  vi.resetModules()
  return import('./theme')
}

const html = document.documentElement

describe('theme', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('follows the system by default, live', async () => {
    const theme = await loadTheme()

    theme.initTheme()
    expect(html).not.toHaveClass('dark')
    expect(html.style.colorScheme).toBe('light')

    setPrefersDark(true)
    expect(html).toHaveClass('dark')
    expect(theme.resolveTheme('system')).toBe('dark')
  })

  it('remembers an explicit choice and ignores the system then', async () => {
    const theme = await loadTheme()
    theme.initTheme()

    theme.setThemePreference('dark')
    setPrefersDark(false)

    expect(html).toHaveClass('dark')
    expect(window.localStorage.getItem('voice-tutor:theme')).toBe('dark')

    const reloaded = await loadTheme()
    reloaded.initTheme()
    expect(html).toHaveClass('dark')
  })

  it('ignores unknown stored values', async () => {
    window.localStorage.setItem('voice-tutor:theme', 'purple')
    const theme = await loadTheme()

    const { result } = renderHook(() => theme.useTheme())

    expect(result.current.preference).toBe('system')
  })

  it('works without storage', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError')
    })
    const theme = await loadTheme()
    const { result, unmount } = renderHook(() => theme.useTheme())

    act(() => {
      result.current.setPreference('dark')
    })

    expect(result.current).toMatchObject({ preference: 'dark', theme: 'dark' })
    unmount()
  })
})

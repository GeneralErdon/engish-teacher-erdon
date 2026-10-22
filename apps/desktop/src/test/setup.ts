import '@testing-library/jest-dom/vitest'
import { cleanup, configure } from '@testing-library/react'
import { MotionGlobalConfig } from 'motion/react'
import { afterEach } from 'vitest'

import { installMatchMedia, resetMatchMedia } from './match-media'

// `findBy*` waits up to 3 s (default 1 s): the whole suite under coverage can be slow on CI.
configure({ asyncUtilTimeout: 3_000 })

// Animations finish instantly: tests assert end states, not frames.
MotionGlobalConfig.skipAnimations = true

// jsdom lacks the browser APIs Radix and the theme code rely on.
class ResizeObserverStub {
  observe = () => undefined
  unobserve = () => undefined
  disconnect = () => undefined
}
globalThis.ResizeObserver = ResizeObserverStub

installMatchMedia()
// The router restores scroll positions; jsdom does not implement scrolling.
window.scrollTo = () => undefined
Element.prototype.scrollIntoView = () => undefined

afterEach(() => {
  cleanup()
  window.localStorage.clear()
  document.documentElement.className = ''
  resetMatchMedia()
})

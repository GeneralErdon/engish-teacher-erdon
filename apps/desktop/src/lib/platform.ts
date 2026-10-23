import { isTauri } from '@tauri-apps/api/core'

const LOCAL_API = 'http://localhost:8080'
const SERVER_KEY = 'voice-tutor:server'

export interface BackendContext {
  /** A server chosen in the app (Settings → Backend), saved on this device. */
  saved: string | undefined
  /** `VITE_BACKEND_URL`, if set at build time. */
  configured: string | undefined
  /** Running inside the Tauri app (desktop or Android). */
  inTauri: boolean
  /** `window.location.origin`. */
  origin: string
}

/**
 * Where the api lives.
 *
 * - A server saved in the app wins: the desktop or Android app reaching a computer on the LAN.
 * - Then `VITE_BACKEND_URL`, set at build time.
 * - The Tauri app defaults to the api on this computer.
 * - In a browser, the page's own origin: the browser build is served by the api itself, and the
 *   Vite dev server forwards the api (`server.proxy` in vite.config.ts), which is also how a
 *   phone on the LAN reaches it (`just dev-lan`).
 */
export function resolveBackendUrl(ctx: BackendContext): string {
  const chosen = ctx.saved ?? ctx.configured
  if (chosen) return chosen.replace(/\/+$/, '')
  if (ctx.inTauri) return LOCAL_API
  return ctx.origin
}

/** Storage can be unavailable (private windows, blocked site data): then nothing is saved. */
export function savedServer(): string | undefined {
  try {
    return window.localStorage.getItem(SERVER_KEY) ?? undefined
  } catch {
    return undefined
  }
}

/** Save the server for this device, or forget it with `null`. */
export function saveServer(url: string | null) {
  try {
    if (url === null) window.localStorage.removeItem(SERVER_KEY)
    else window.localStorage.setItem(SERVER_KEY, url)
  } catch {
    // Nothing to remember it in: the app keeps its default.
  }
}

/**
 * What a learner types, as a server URL: `192.168.0.10:8080` becomes `http://192.168.0.10:8080`.
 * `undefined` if it is not an http(s) address.
 */
export function normalizeServer(input: string): string | undefined {
  const text = input.trim()
  if (!text) return undefined
  try {
    const url = new URL(/^[a-z][a-z\d+.-]*:\/\//i.test(text) ? text : `http://${text}`)
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return undefined
    return `${url.origin}${url.pathname}`.replace(/\/+$/, '')
  } catch {
    return undefined
  }
}

export function backendUrl(): string {
  return resolveBackendUrl({
    saved: savedServer(),
    configured: import.meta.env.VITE_BACKEND_URL,
    inTauri: isTauri(),
    origin: window.location.origin,
  })
}

/** The installed app (desktop or Android), which can point at another computer. */
export function inApp(): boolean {
  return isTauri()
}

/** Start over with the new server: every client and socket picks it up on load. */
export function reloadApp() {
  window.location.reload()
}

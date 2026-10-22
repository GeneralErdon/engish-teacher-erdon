import { isTauri } from '@tauri-apps/api/core'

const LOCAL_API = 'http://localhost:8080'

export interface BackendContext {
  /** `VITE_BACKEND_URL`, if set at build time. */
  configured: string | undefined
  /** Running inside the Tauri desktop shell. */
  inTauri: boolean
  /** `window.location.origin`. */
  origin: string
}

/**
 * Where the api lives.
 *
 * - An explicit `VITE_BACKEND_URL` always wins.
 * - The desktop app talks to the local api.
 * - In a browser, the page's own origin: the browser build is served by the api itself, and the
 *   Vite dev server forwards the api (`server.proxy` in vite.config.ts), which is also how a
 *   phone on the LAN reaches it (`just dev-lan`).
 */
export function resolveBackendUrl(ctx: BackendContext): string {
  if (ctx.configured) return ctx.configured.replace(/\/+$/, '')
  if (ctx.inTauri) return LOCAL_API
  return ctx.origin
}

export function backendUrl(): string {
  return resolveBackendUrl({
    configured: import.meta.env.VITE_BACKEND_URL,
    inTauri: isTauri(),
    origin: window.location.origin,
  })
}

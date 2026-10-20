import { isTauri } from '@tauri-apps/api/core'

const LOCAL_API = 'http://localhost:8080'

export interface BackendContext {
  /** `VITE_BACKEND_URL`, if set at build time. */
  configured: string | undefined
  /** Running inside the Tauri desktop shell. */
  inTauri: boolean
  /** Vite dev server (`just dev`). */
  dev: boolean
  /** `window.location.origin`. */
  origin: string
}

/**
 * Where the api lives.
 *
 * - An explicit `VITE_BACKEND_URL` always wins.
 * - The desktop app and the Vite dev server talk to the local api.
 * - The browser build is served by the api itself, so it uses its own origin.
 */
export function resolveBackendUrl(ctx: BackendContext): string {
  if (ctx.configured) return ctx.configured.replace(/\/+$/, '')
  if (ctx.inTauri || ctx.dev) return LOCAL_API
  return ctx.origin
}

export function backendUrl(): string {
  return resolveBackendUrl({
    configured: import.meta.env.VITE_BACKEND_URL,
    inTauri: isTauri(),
    dev: import.meta.env.DEV,
    origin: window.location.origin,
  })
}

interface ImportMetaEnv {
  /** Overrides where the api lives (e.g. a home-lab server). See `src/lib/platform.ts`. */
  readonly VITE_BACKEND_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

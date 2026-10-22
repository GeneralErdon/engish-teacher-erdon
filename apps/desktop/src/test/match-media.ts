type Listener = (event: MediaQueryListEvent) => void

let prefersDark = false
const listeners = new Set<Listener>()

/** A `matchMedia` for `prefers-color-scheme` that tests can flip (jsdom has none). */
export function installMatchMedia() {
  window.matchMedia = (query: string) =>
    ({
      get matches() {
        return query.includes('dark') && prefersDark
      },
      media: query,
      addEventListener: (_type: string, listener: Listener) => listeners.add(listener),
      removeEventListener: (_type: string, listener: Listener) => listeners.delete(listener),
    }) as unknown as MediaQueryList
}

/** Simulate the OS switching between light and dark. */
export function setPrefersDark(dark: boolean) {
  prefersDark = dark
  for (const listener of listeners) listener({ matches: dark } as MediaQueryListEvent)
}

export function resetMatchMedia() {
  prefersDark = false
  listeners.clear()
}

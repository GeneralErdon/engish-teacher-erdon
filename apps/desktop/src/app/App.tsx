import { useEffect, useState } from 'react'

import { fetchHealth, type HealthResponse } from '../lib/health'
import { backendUrl } from '../lib/platform'

type HealthState =
  | { kind: 'checking' }
  | { kind: 'online'; health: HealthResponse }
  | { kind: 'offline'; reason: string }

export interface AppProps {
  apiUrl?: string
}

export function App({ apiUrl = backendUrl() }: AppProps) {
  const [state, setState] = useState<HealthState>({ kind: 'checking' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    fetchHealth(apiUrl, controller.signal)
      .then((health) => {
        setState({ kind: 'online', health })
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setState({ kind: 'offline', reason: error instanceof Error ? error.message : 'unknown' })
      })
    return () => {
      controller.abort()
    }
  }, [apiUrl, attempt])

  const retry = () => {
    setState({ kind: 'checking' })
    setAttempt((n) => n + 1)
  }

  return (
    <main className="shell">
      <header>
        <h1>voice-tutor</h1>
        <p className="tagline">Your private English speaking coach</p>
      </header>

      <section className="status" aria-live="polite" data-state={state.kind}>
        <span className="dot" aria-hidden="true" />
        {state.kind === 'checking' && <p>Checking the API…</p>}
        {state.kind === 'online' && (
          <p>
            API online <span className="muted">· v{state.health.version}</span>
          </p>
        )}
        {state.kind === 'offline' && (
          <div>
            <p>API unreachable</p>
            <p className="muted">
              {state.reason}. Start it with <code>just dev-api</code> or <code>just up</code>.
            </p>
          </div>
        )}
      </section>

      <footer>
        <code className="muted">{apiUrl}</code>
        <button type="button" onClick={retry} disabled={state.kind === 'checking'}>
          Retry
        </button>
      </footer>
    </main>
  )
}

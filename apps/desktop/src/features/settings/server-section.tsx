import { RotateCcw } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { BackendStatus } from '@/features/status/backend-status'
import {
  backendUrl,
  inApp,
  normalizeServer,
  reloadApp,
  saveServer,
  savedServer,
} from '@/lib/platform'

const CHECK_TIMEOUT_MS = 5_000

/**
 * Where the app finds the tutor. In a browser, the page's own server. In the installed app
 * (desktop or Android), any computer on the network: checked, saved on this device, then the app
 * reloads to use it.
 */
export function ServerSection() {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <code className="bg-muted rounded-md px-2 py-1">{backendUrl()}</code>
        <BackendStatus />
      </div>
      {inApp() && <ServerForm />}
    </div>
  )
}

function ServerForm() {
  const saved = savedServer()
  const [address, setAddress] = useState(saved ?? '')
  const [checking, setChecking] = useState(false)
  const [error, setError] = useState<string>()

  const save = async () => {
    const url = normalizeServer(address)
    if (!url) {
      setError('Enter the address of the computer running the tutor, like 192.168.0.10:8080.')
      return
    }
    setError(undefined)
    setChecking(true)
    try {
      const response = await fetch(
        new Request(`${url}/healthz`, { signal: AbortSignal.timeout(CHECK_TIMEOUT_MS) }),
      )
      if (!response.ok) throw new Error(`HTTP ${String(response.status)}`)
    } catch {
      setChecking(false)
      setError(
        `No tutor answered at ${url}. Is the api running there, listening on the network (just dev-api 0.0.0.0), and is this device on the same network?`,
      )
      return
    }
    saveServer(url)
    reloadApp()
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        void save()
      }}
      className="flex flex-col gap-2"
    >
      <label htmlFor="server" className="text-sm font-medium">
        Server address
      </label>
      <div className="flex flex-wrap gap-2">
        <input
          id="server"
          inputMode="url"
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          placeholder="192.168.0.10:8080"
          value={address}
          onChange={(event) => {
            setAddress(event.target.value)
          }}
          aria-invalid={error !== undefined}
          aria-describedby="server-hint"
          className="border-input bg-background focus-visible:ring-ring/50 h-9 min-w-0 flex-1 rounded-md border px-3 text-sm outline-none focus-visible:ring-[3px]"
        />
        <Button type="submit" disabled={checking}>
          {checking ? 'Checking…' : 'Check and use'}
        </Button>
        {saved && (
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              saveServer(null)
              reloadApp()
            }}
          >
            <RotateCcw /> This computer
          </Button>
        )}
      </div>
      <p
        id="server-hint"
        role={error ? 'alert' : undefined}
        className={error ? 'text-destructive text-sm' : 'text-muted-foreground text-sm'}
      >
        {error ??
          'Empty means this computer. To use the tutor from your phone, run the api on your computer with just dev-api 0.0.0.0 and enter its address here.'}
      </p>
    </form>
  )
}

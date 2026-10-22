import { act } from '@testing-library/react'
import { vi } from 'vitest'

import type { ClientEvent, ServerEvent } from '@/features/practice/use-conversation'

/** A `WebSocket` stand-in: records what the UI sends and lets tests push server events. */
export class FakeSocket {
  static instances: FakeSocket[] = []

  readonly url: string
  readonly sent: ClientEvent[] = []
  /** Binary frames (microphone audio). */
  readonly audio: ArrayBuffer[] = []
  closed = false
  onopen: ((event: Event) => void) | null = null
  onmessage: ((event: MessageEvent<string>) => void) | null = null
  onclose: ((event: CloseEvent) => void) | null = null

  constructor(url: string) {
    this.url = url
    FakeSocket.instances.push(this)
  }

  static get last(): FakeSocket {
    const socket = FakeSocket.instances.at(-1)
    if (!socket) throw new Error('no socket was opened')
    return socket
  }

  send(data: string | ArrayBuffer) {
    if (typeof data === 'string') this.sent.push(JSON.parse(data) as ClientEvent)
    else this.audio.push(data)
  }

  close() {
    this.closed = true
  }

  // ------------------------------------------------------------ test controls

  open() {
    act(() => {
      this.onopen?.(new Event('open'))
    })
  }

  emit(...events: ServerEvent[]) {
    act(() => {
      for (const event of events) {
        this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(event) }))
      }
    })
  }

  /** The server went away. */
  drop() {
    act(() => {
      this.onclose?.(new CloseEvent('close'))
    })
  }
}

export function installFakeSocket() {
  FakeSocket.instances = []
  vi.stubGlobal('WebSocket', FakeSocket)
}

import { act, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { App } from './App'

const healthy = { status: 'ok', service: 'api', version: '0.1.0' }

describe('App', () => {
  it('shows the api version when /healthz answers', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json(healthy)))

    render(<App apiUrl="http://localhost:8080" />)

    expect(await screen.findByText('API online')).toBeInTheDocument()
    expect(screen.getByText('· v0.1.0')).toBeInTheDocument()
  })

  it('explains how to start the api when it is unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

    render(<App apiUrl="http://localhost:8080" />)

    expect(await screen.findByText('API unreachable')).toBeInTheDocument()
    expect(screen.getByText(/Failed to fetch/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeEnabled()
  })

  it('reports failures that are not Error objects', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue('boom'))

    render(<App apiUrl="http://localhost:8080" />)

    expect(await screen.findByText(/unknown/)).toBeInTheDocument()
  })

  it('checks again when Retry is pressed', async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce(Response.json(healthy))
    vi.stubGlobal('fetch', fetchMock)
    render(<App apiUrl="http://localhost:8080" />)

    const retry = await screen.findByRole('button', { name: 'Retry' })
    act(() => {
      retry.click()
    })

    expect(await screen.findByText('API online')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('defaults to the backend for the current platform', async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json(healthy))
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    expect(await screen.findByText('API online')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith('http://localhost:8080/healthz', expect.anything())
  })

  it('ignores the answer of a check it already cancelled', async () => {
    let rejectFetch: (reason: unknown) => void = () => undefined
    vi.stubGlobal(
      'fetch',
      vi.fn(
        () =>
          new Promise((_resolve, reject) => {
            rejectFetch = reject
          }),
      ),
    )
    const { unmount } = render(<App apiUrl="http://localhost:8080" />)

    unmount()
    await act(async () => {
      rejectFetch(new DOMException('aborted', 'AbortError'))
      await Promise.resolve()
    })

    expect(screen.queryByText('API unreachable')).not.toBeInTheDocument()
  })
})

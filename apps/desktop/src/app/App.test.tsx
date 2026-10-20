import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { App } from './App'

describe('App', () => {
  it('shows the api version when /healthz answers', async () => {
    const health = { status: 'ok', service: 'api', version: '0.1.0' }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json(health)))

    render(<App apiUrl="http://localhost:8080" />)

    expect(await screen.findByText('API online')).toBeInTheDocument()
    expect(screen.getByText('· v0.1.0')).toBeInTheDocument()
  })

  it('explains how to start the api when it is unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

    render(<App apiUrl="http://localhost:8080" />)

    expect(await screen.findByText('API unreachable')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeEnabled()
  })
})

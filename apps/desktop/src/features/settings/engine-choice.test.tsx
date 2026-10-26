import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { EngineChoice } from './engine-choice'

const engines = (gpuRunning: boolean) => [
  { engine: 'openai' as const, running: true, manageable: true },
  { engine: 'whispercpp' as const, running: gpuRunning, manageable: true },
]

describe('EngineChoice', () => {
  it('shows both engines, and disables the stopped one with how to start it', () => {
    render(<EngineChoice engines={engines(false)} value="openai" onChange={vi.fn()} />)

    const group = screen.getByRole('radiogroup', { name: 'Speech recognition engine' })
    expect(group).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: 'Speaches · CPU' })).toBeChecked()
    expect(screen.getByRole('radio', { name: 'whisper.cpp · GPU' })).toBeDisabled()
    expect(
      screen.getByText('Start it with `just voice gpu` (Linux, AMD or Intel GPU)'),
    ).toBeInTheDocument()
    expect(screen.getByText('Uses an NVIDIA GPU with the `nvidia` profile')).toBeInTheDocument()
  })

  it('chooses the other engine once it runs', async () => {
    const onChange = vi.fn()
    render(<EngineChoice engines={engines(true)} value="openai" onChange={onChange} />)

    expect(screen.getByText('AMD and Intel GPUs, through Vulkan')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('radio', { name: 'whisper.cpp · GPU' }))

    expect(onChange).toHaveBeenCalledWith('whispercpp')
  })
})

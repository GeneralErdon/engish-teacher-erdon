import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { EngineChoice } from './engine-choice'

const engines = (gpuRunning: boolean, speachesRunning = true) => [
  { engine: 'openai' as const, running: speachesRunning, manageable: true },
  { engine: 'whispercpp' as const, running: gpuRunning, manageable: true },
]

/** The command in a hint, shown as code. */
function expectCode(text: string) {
  expect(screen.getByText(text).tagName).toBe('CODE')
}

describe('EngineChoice', () => {
  it('shows both engines, and disables the stopped one with how to start it', () => {
    render(<EngineChoice engines={engines(false)} value="openai" onChange={vi.fn()} />)

    const group = screen.getByRole('radiogroup', { name: 'Speech recognition engine' })
    expect(group).toBeInTheDocument()
    const speaches = screen.getByRole('radio', { name: 'Speaches · CPU' })
    expect(speaches).toBeChecked()
    expect(speaches).toHaveAccessibleDescription('Uses an NVIDIA GPU with the nvidia profile')
    expectCode('nvidia')
    const gpu = screen.getByRole('radio', { name: 'whisper.cpp · GPU' })
    expect(gpu).toBeDisabled()
    expect(gpu).toHaveAccessibleDescription(
      'Start it with just voice gpu (Linux, AMD or Intel GPU)',
    )
    expectCode('just voice gpu')
    expect(screen.queryByText(/`/)).not.toBeInTheDocument()
  })

  it('says how to start Speaches when it is stopped', () => {
    render(<EngineChoice engines={engines(true, false)} value="whispercpp" onChange={vi.fn()} />)

    const speaches = screen.getByRole('radio', { name: 'Speaches · CPU' })
    expect(speaches).toBeDisabled()
    expect(speaches).toHaveAccessibleDescription('Start it with just voice')
    expectCode('just voice')
    expect(screen.queryByText('nvidia')).not.toBeInTheDocument()
  })

  it('chooses the other engine once it runs', async () => {
    const onChange = vi.fn()
    render(<EngineChoice engines={engines(true)} value="openai" onChange={onChange} />)

    expect(screen.getByText('AMD and Intel GPUs, through Vulkan')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('radio', { name: 'whisper.cpp · GPU' }))

    expect(onChange).toHaveBeenCalledWith('whispercpp')
  })
})

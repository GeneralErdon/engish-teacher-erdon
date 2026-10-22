import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { fakeApi, pending } from '@/test/fake-api'
import { renderApp } from '@/test/render-app'

import { languageName } from './use-learner'

const failure = (status: number, detail: string) => () => Response.json({ detail }, { status })

describe('Learning settings', () => {
  it('saves the level and the explanation language as soon as they change', async () => {
    const { user, api } = renderApp('/settings')
    const level = await screen.findByRole('radiogroup', { name: 'Level' })
    expect(within(level).getByRole('radio', { name: 'B1' })).toBeChecked()

    await user.click(within(level).getByRole('radio', { name: 'C1' }))
    expect(await screen.findByText('Saved')).toBeInTheDocument()

    const explanations = screen.getByRole('radiogroup', { name: 'Explanations' })
    expect(within(explanations).getByRole('radio', { name: 'Spanish' })).toBeChecked()
    await user.click(within(explanations).getByRole('radio', { name: 'English' }))

    expect(await within(explanations).findByRole('radio', { name: 'English' })).toBeChecked()
    expect(api.sent.get('PUT /v1/learner')).toEqual([
      { level: 'C1', explanations: 'native' },
      { level: 'C1', explanations: 'english' },
    ])
  })

  it('shows saving and failures', async () => {
    const { user } = renderApp('/settings', fakeApi({ saveLearner: failure(500, 'disk full') }))
    const level = await screen.findByRole('radiogroup', { name: 'Level' })

    await user.click(within(level).getByRole('radio', { name: 'A2' }))

    expect(await screen.findByText('disk full')).toBeInTheDocument()
  })

  it('locks the controls while saving', async () => {
    const { user } = renderApp('/settings', fakeApi({ saveLearner: pending }))
    const level = await screen.findByRole('radiogroup', { name: 'Level' })

    await user.click(within(level).getByRole('radio', { name: 'A2' }))

    expect(await screen.findByText('Saving…')).toBeInTheDocument()
    expect(within(level).getByRole('radio', { name: 'A2' })).toBeDisabled()
  })

  it('reports a profile it cannot load', async () => {
    renderApp('/settings', fakeApi({ learner: failure(500, 'boom') }))

    expect(await screen.findByText('boom')).toBeInTheDocument()
  })

  it('shows a placeholder while loading', async () => {
    renderApp('/settings', fakeApi({ learner: pending }))

    expect((await screen.findAllByLabelText('Loading')).length).toBeGreaterThan(0)
  })

  it('names languages in English', () => {
    expect(languageName('es')).toBe('Spanish')
    expect(languageName('pt')).toBe('Portuguese')
  })
})

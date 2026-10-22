import { describe, expect, it } from 'vitest'

import { ApiError, errorMessage, toApiError } from './errors'

describe('toApiError', () => {
  it('uses FastAPI string details', () => {
    const error = toApiError(422, { detail: 'Ollama Cloud needs an API key.' })

    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(422)
    expect(error.message).toBe('Ollama Cloud needs an API key.')
  })

  it('joins validation issues', () => {
    const body = { detail: [{ msg: 'Field required' }, { loc: ['x'] }, { msg: 'Too long' }] }

    expect(toApiError(422, body).message).toBe('Field required. Too long')
  })

  it.each([null, 'oops', { detail: 42 }, { detail: [] }, { other: 1 }])(
    'falls back to the status for %j',
    (body) => {
      expect(toApiError(502, body).message).toBe('Request failed with HTTP 502')
    },
  )
})

describe('errorMessage', () => {
  it('describes every kind of failure', () => {
    expect(errorMessage(new ApiError(500, 'boom'))).toBe('boom')
    expect(errorMessage(new TypeError('Failed to fetch'))).toBe(
      'Could not reach the api. Is it running?',
    )
    expect(errorMessage(new Error('odd'))).toBe('odd')
    expect(errorMessage('???')).toBe('Something went wrong.')
  })
})

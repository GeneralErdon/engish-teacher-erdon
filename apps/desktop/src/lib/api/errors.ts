/** A non-2xx answer from the api, with the message it sent (FastAPI's `{"detail": ...}`). */
export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

interface ValidationIssue {
  msg: string
}

function isValidationIssue(value: unknown): value is ValidationIssue {
  return (
    typeof value === 'object' && value !== null && 'msg' in value && typeof value.msg === 'string'
  )
}

/** FastAPI sends `detail` as a string, or as a list of validation issues (HTTP 422). */
function detailOf(body: unknown): string | undefined {
  if (typeof body !== 'object' || body === null || !('detail' in body)) return undefined
  const { detail } = body
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const messages = detail.filter(isValidationIssue).map((issue) => issue.msg)
    if (messages.length > 0) return messages.join('. ')
  }
  return undefined
}

export function toApiError(status: number, body: unknown): ApiError {
  return new ApiError(status, detailOf(body) ?? `Request failed with HTTP ${String(status)}`)
}

/** A message to show for any failure: api errors carry theirs, network errors become a hint. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof TypeError) return 'Could not reach the api. Is it running?'
  return error instanceof Error ? error.message : 'Something went wrong.'
}

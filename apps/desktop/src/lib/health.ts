/**
 * Mirrors `vt_contracts.health.HealthResponse`.
 * Phase 1 replaces it with the types generated from the contracts (`just types`).
 */
export interface HealthResponse {
  status: 'ok'
  service: 'api' | 'pron'
  version: string
}

export function isHealthResponse(value: unknown): value is HealthResponse {
  return (
    typeof value === 'object' &&
    value !== null &&
    'status' in value &&
    value.status === 'ok' &&
    'service' in value &&
    (value.service === 'api' || value.service === 'pron') &&
    'version' in value &&
    typeof value.version === 'string'
  )
}

export async function fetchHealth(baseUrl: string, signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch(`${baseUrl}/healthz`, { signal: signal ?? null })
  if (!response.ok) {
    throw new Error(`GET /healthz failed with HTTP ${String(response.status)}`)
  }
  const body: unknown = await response.json()
  if (!isHealthResponse(body)) {
    throw new Error('GET /healthz returned an unexpected body')
  }
  return body
}

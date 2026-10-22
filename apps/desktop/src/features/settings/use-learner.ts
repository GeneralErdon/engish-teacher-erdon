import { api } from '@/lib/api/client'

export const learnerQuery = api.queryOptions('get', '/v1/learner')

/** "es" → "Spanish". */
export function languageName(code: string) {
  return new Intl.DisplayNames(['en'], { type: 'language' }).of(code) ?? code
}

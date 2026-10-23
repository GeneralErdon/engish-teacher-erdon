import { z } from 'zod'

import type { ProviderKind } from './use-llm'

export const PROVIDER_KINDS = [
  'ollama',
  'ollama_cloud',
  'openai',
  'anthropic',
  'gemini',
  'openai_compatible',
  'anthropic_compatible',
] as const satisfies readonly ProviderKind[]

/** What the form needs to know about keys, which changes with the saved settings. */
export interface KeyRules {
  requiresKey: (kind: ProviderKind) => boolean
  /** A key was saved for this provider *and this URL*: the api reuses it if the field is empty. */
  hasSavedKey: (kind: ProviderKind, baseUrl: string) => boolean
}

/** The api stores URLs without a trailing slash; compare them the same way. */
export function normalizeUrl(url: string) {
  return url.trim().replace(/\/+$/, '')
}

export function languageModelSchema(rules: KeyRules) {
  return z
    .object({
      kind: z.enum(PROVIDER_KINDS),
      base_url: z
        .string()
        .trim()
        .min(1, 'Enter the base URL.')
        .pipe(z.url({ protocol: /^https?$/, error: 'Enter an http:// or https:// URL.' })),
      api_key: z.string().trim().max(500, 'That key is too long.'),
      model: z
        .string()
        .trim()
        .min(1, 'Pick or type a model.')
        .max(200, 'That name is too long.')
        .regex(/^\S+$/, 'Model names have no spaces.'),
    })
    .refine(
      (values) =>
        !rules.requiresKey(values.kind) ||
        values.api_key !== '' ||
        rules.hasSavedKey(values.kind, normalizeUrl(values.base_url)),
      {
        path: ['api_key'],
        error: 'This provider needs an API key.',
        // Also check the key while other fields (the model, say) are still invalid.
        when: ({ issues }) =>
          !issues.some((issue) => ['kind', 'api_key'].includes(String(issue.path?.[0]))),
      },
    )
}

export type LanguageModelValues = z.input<ReturnType<typeof languageModelSchema>>

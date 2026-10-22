import js from '@eslint/js'
import prettier from 'eslint-config-prettier/flat'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'
import globals from 'globals'
import tseslint from 'typescript-eslint'

export default defineConfig(
  globalIgnores(['dist', 'coverage', 'src-tauri', 'src/generated']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.strictTypeChecked,
      tseslint.configs.stylisticTypeChecked,
      reactHooks.configs.flat['recommended-latest'],
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
  },
  {
    files: ['**/*.{ts,tsx}'],
    rules: {
      // Conflicts with `no-non-null-assertion` (strict), which wins: prefer explicit casts to `!`.
      '@typescript-eslint/non-nullable-type-assertion-style': 'off',
      // `''` is "not set" in form fields and API strings, so `||` on strings is intended.
      '@typescript-eslint/prefer-nullish-coalescing': [
        'error',
        { ignorePrimitives: { string: true } },
      ],
    },
  },
  {
    // shadcn/ui components export their `cva` variants next to the component, by design.
    files: ['src/components/ui/**/*.tsx'],
    rules: {
      'react-refresh/only-export-components': [
        'error',
        { allowExportNames: ['buttonVariants', 'badgeVariants'] },
      ],
    },
  },
  {
    // Audio worklets: plain JavaScript modules for the audio thread (see the file header).
    files: ['public/**/*.worklet.js'],
    extends: [js.configs.recommended],
    languageOptions: { globals: globals.audioWorklet },
  },
  // Last: turn off stylistic rules that Prettier owns.
  prettier,
)

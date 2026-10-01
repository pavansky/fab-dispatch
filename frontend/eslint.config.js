import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'

export default [
  { ignores: ['dist', 'node_modules', 'coverage', 'playwright-report', 'test-results'] },
  {
    files: ['**/*.{js,jsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: { ...globals.browser },
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    plugins: { 'react-hooks': reactHooks, 'react-refresh': reactRefresh },
    rules: {
      ...js.configs.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      'no-unused-vars': ['error', { varsIgnorePattern: '^[A-Z_]', argsIgnorePattern: '^_' }],
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true, allowExportNames: ['useAuth', 'useTooltip'] }],
    },
  },
  {
    files: ['**/__tests__/**', 'src/test/**', '**/*.test.{js,jsx}', 'e2e/**', 'vite.config.js', 'eslint.config.js', 'playwright.config.js'],
    languageOptions: { globals: { ...globals.node } },
    rules: { 'react-refresh/only-export-components': 'off' },
  },
  // Playwright fixtures call `use()`, which isn't React's hook.
  { files: ['e2e/**'], rules: { 'react-hooks/rules-of-hooks': 'off' } },
]

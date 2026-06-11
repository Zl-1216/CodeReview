// Flat config (ESLint v9). We lint JS + Vue SFCs in `src/` and tests.
// Run with: npm run lint
import js from '@eslint/js'
import vue from 'eslint-plugin-vue'
import globals from 'globals'

export default [
  // Ignore generated / vendored paths
  {
    ignores: [
      'node_modules/**',
      'dist/**',
      'public/**',
      '*.config.js',
      'vitest.config.js',
    ],
  },

  // JS / JSX baseline
  js.configs.recommended,

  // Vue plugin defaults
  ...vue.configs['flat/recommended'],

  // Project rules
  {
    files: ['src/**/*.{js,vue}'],
    languageOptions: {
      ecmaVersion: 2024,
      sourceType: 'module',
      globals: {
        ...globals.browser,
        ...globals.node,
      },
    },
    rules: {
      // Vue 3 + Composition API: don't require Options API patterns
      'vue/multi-word-component-names': 'off',
      'vue/no-v-html': 'off',  // CodeView renders raw user-supplied code; intentional
      'vue/require-default-prop': 'off',  // not idiomatic in Vue 3 + script setup
      // Stylistic: don't fight Prettier's decisions on inline layout
      'vue/max-attributes-per-line': 'off',
      'vue/singleline-html-element-content-newline': 'off',
      'vue/html-self-closing': 'off',
      'vue/attributes-order': 'off',
      'vue/first-attribute-linebreak': 'off',
      'no-unused-vars': ['warn', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      // Empty catch blocks in api.js: non-fatal JSON parse failures are an
      // accepted pattern; require a comment when intentionally empty.
      'no-empty': ['error', { allowEmptyCatch: true }],
    },
  },

  // Tests are allowed to use the vitest globals and a few undeclared patterns
  {
    files: ['src/**/*.test.js', 'src/**/*.spec.js'],
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.node,
      },
    },
    rules: {},
  },
]

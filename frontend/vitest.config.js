import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

// Separate from vite.config.js so dev server / build stay untouched.
// We pull in the Vue plugin because some tests mount components via
// @vue/test-utils.
export default defineConfig({
  plugins: [vue()],
  test: {
    environment: 'happy-dom',
    globals: false,
    include: ['src/**/*.{test,spec}.{js,ts}'],
    clearMocks: true,
  },
})

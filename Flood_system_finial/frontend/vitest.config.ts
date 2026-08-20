import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Vitest config kept SEPARATE from vite.config.ts: Vite 8's own
// `UserConfigExport` type has no `test` key, so inlining it there is a
// real `tsc` error (TS2769) rather than just a lint nit. `vitest/config`
// re-exports a `defineConfig` that does know about `test`.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
  },
})

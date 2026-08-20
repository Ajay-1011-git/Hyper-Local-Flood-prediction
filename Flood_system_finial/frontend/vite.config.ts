import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Tailwind v4 is a Vite PLUGIN, not the older PostCSS/`npx tailwindcss init`
// flow — confirmed against tailwindcss.com/docs/installation/using-vite in
// this session (T4B.0), not assumed from memory.
//
// Vitest config lives separately in vitest.config.ts — see that file for
// why (Vite 8's UserConfigExport type has no `test` key).
export default defineConfig({
  plugins: [react(), tailwindcss()],
})

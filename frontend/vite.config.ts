/// <reference types="vitest/config" />
// Vite build + dev-proxy + Vitest configuration for the Spyglass dashboard SPA.
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Port of the Python service that /api is proxied to in dev mode. Set SPYGLASS_PORT when the
// service runs somewhere other than the default 7777; an unusable value falls back to 7777.
const parsedPort = Number(process.env.SPYGLASS_PORT)
const servicePort = Number.isInteger(parsedPort) && parsedPort > 0 && parsedPort < 65536 ? parsedPort : 7777

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Dev mode: the Python service owns /api; Vite serves the SPA with HMR.
    proxy: {
      '/api': { target: `http://localhost:${servicePort}`, changeOrigin: true },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: true,
    coverage: {
      provider: 'v8',
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/main.tsx', 'src/test/**'],
      // Project rule: 80 percent minimum coverage.
      thresholds: { lines: 80, functions: 80, branches: 80, statements: 80 },
    },
  },
})

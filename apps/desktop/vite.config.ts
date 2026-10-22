/// <reference types="vitest/config" />
import { fileURLToPath } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import { tanstackRouter } from '@tanstack/router-plugin/vite'
import basicSsl from '@vitejs/plugin-basic-ssl'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Set by `tauri dev` when the app runs on a device (mobile / remote debugging); unset on desktop.
const host = process.env.TAURI_DEV_HOST
// The api the dev server forwards to (`just dev-api`).
const api = process.env.VT_API_URL ?? 'http://localhost:8080'
// `just dev-lan`: HTTPS with a self-signed certificate, because phones only open the microphone
// on secure pages (`http://localhost` counts as secure; `http://192.168.x.x` does not).
const https = process.env.VT_DEV_HTTPS === '1'

// https://v2.tauri.app/start/frontend/vite/
export default defineConfig({
  plugins: [
    tailwindcss(),
    // Generates the route tree from src/routes and splits each page into its own chunk.
    // Must run before the React plugin.
    tanstackRouter({
      target: 'react',
      autoCodeSplitting: true,
      generatedRouteTree: './src/generated/routeTree.gen.ts',
    }),
    react(),
    ...(https ? [basicSsl({ name: 'voice-tutor' })] : []),
  ],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  // Keep Rust compiler errors visible in the `tauri dev` terminal.
  clearScreen: false,
  server: {
    // Tauri's `build.devUrl` expects this exact port.
    port: 1420,
    strictPort: true,
    host: host ?? false,
    ...(host ? { hmr: { protocol: 'ws', host, port: 1421 } } : {}),
    watch: { ignored: ['**/src-tauri/**'] },
    // The page talks to the api through this server, on its own origin: no CORS, and a phone on
    // the LAN reaches the api while the api itself listens on localhost only. The Host header is
    // kept, so the api's WebSocket origin check sees a same-origin page.
    proxy: {
      '/v1': api,
      '/healthz': api,
      '/ws': { target: api, ws: true },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    restoreMocks: true,
    unstubGlobals: true,
    unstubEnvs: true,
    coverage: {
      provider: 'v8',
      reportsDirectory: './coverage',
      reporter: ['text', 'lcov', 'html'],
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        // Entrypoint: mounts <App /> into index.html; everything it renders is tested.
        'src/main.tsx',
        // Test apparatus and type-only declarations, not code under test.
        'src/test/**',
        'src/**/*.test.{ts,tsx}',
        'src/**/*.d.ts',
        // Generated: API types (`just types`) and the route tree (TanStack Router plugin).
        'src/generated/**',
        // Route declarations: the router plugin rewrites their `component` for code splitting
        // and hot reload, so v8 cannot map those lines. The pages they render are tested.
        'src/routes/**',
      ],
      // A floor, not a target: never lower it to make a build pass (docs/development.md#testing).
      thresholds: {
        lines: 97,
        functions: 97,
        branches: 97,
        statements: 97,
      },
    },
  },
})

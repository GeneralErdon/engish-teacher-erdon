/// <reference types="vitest/config" />
import { fileURLToPath } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import { tanstackRouter } from '@tanstack/router-plugin/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Set by `tauri dev` when the app runs on a device (mobile / remote debugging); unset on desktop.
const host = process.env.TAURI_DEV_HOST

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

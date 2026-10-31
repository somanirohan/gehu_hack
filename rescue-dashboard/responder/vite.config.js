import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The responder site is served at /responder/ by the backend.
// In development it runs on port 5174 and forwards API calls to the backend.
const backend = process.env.BACKEND || 'http://localhost:8001'

export default defineConfig({
  base: '/responder/',
  plugins: [react()],
  server: {
    port: 5174,
    host: true, // reachable from phones on the same network during testing
    proxy: {
      '/api': backend,
      '/media': backend,
      '/ws': { target: backend.replace('http', 'ws'), ws: true },
    },
  },
})

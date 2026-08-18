import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ command }) => ({
  base: command === 'build' ? '/canvas/' : '/',
  plugins: [react()],
  build: {
    // This local single-user tool accepts the current bundle size; future real slimming should lazy-load markdown/highlight and trim the hljs language subset.
    chunkSizeWarningLimit: 800,
  },
  server: {
    host: '127.0.0.1',
    proxy: {
      '/api': 'http://localhost:8890',
    },
  },
}));

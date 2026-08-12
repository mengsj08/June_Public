import { defineConfig } from 'vite';

export default defineConfig(({ mode }) => ({
  build: {
    lib: {
      entry: 'src/index.js',
      formats: ['es'],
      fileName: () => 'comma-editor.js',
    },
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: mode !== 'chrome',
    target: 'es2022',
  },
  server: {
    host: '127.0.0.1',
  },
}));

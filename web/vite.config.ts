import { defineConfig } from 'vite';

export default defineConfig({
  publicDir: '../data/app-public',
  build: { outDir: '../data/app-dist', emptyOutDir: true },
  server: { host: '127.0.0.1', port: 5173, strictPort: true },
});

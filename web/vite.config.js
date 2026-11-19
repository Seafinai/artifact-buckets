import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

// AB_API points the dev server at another backend, e.g. a test server's HTTPS through an SSH forward; AB_API_HOST
// is the name that server answers to, when it differs from the forward's address.
const api = process.env.AB_API || 'http://127.0.0.1:8080';
const host = process.env.AB_API_HOST;
const proxy = Object.fromEntries(['/api', '/oauth', '/mcp', '/preview', '/auth/oidc', '/.well-known', '/healthz']
  .map((p) => [p, { target: api, changeOrigin: !host, secure: false, ...(host ? { headers: { host } } : {}) }]));

export default defineConfig({
  plugins: [svelte()],
  server: { port: 5173, proxy },
  build: { outDir: 'dist', assetsInlineLimit: 0, sourcemap: false },
});

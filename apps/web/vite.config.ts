import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';
import { paraglideVitePlugin } from '@inlang/paraglide-js';

export default defineConfig({
  plugins: [
    paraglideVitePlugin({
      project: './project.inlang',
      outdir: './src/lib/paraglide',
      cleanOutdir: false,
      strategy: ['url', 'cookie', 'baseLocale'],
      // URL patterns: both /en/ and /ja/ prefixes always present.
      // The base locale (English) also gets the /en/ prefix.
      urlPatterns: [
        {
          pattern: ':protocol://:domain(.*)::port?/:path(.*)?',
          localized: [
            ['en', ':protocol://:domain(.*)::port?/en/:path(.*)?'],
            ['ja', ':protocol://:domain(.*)::port?/ja/:path(.*)?'],
          ],
        },
      ],
    }),
    sveltekit(),
  ],
  optimizeDeps: {
    include: ['maplibre-gl'],
    esbuildOptions: {
      target: 'es2022',
    },
  },
  build: {
    target: 'es2022',
  },
  test: {
    include: ['src/**/*.{test,spec}.{js,ts}'],
    globals: true,
    environment: 'jsdom'
  },
  server: {
    port: 5173,
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: process.env.ECHOROO_API_URL || 'http://localhost:8002',
        changeOrigin: true
      },
      // DEV ONLY: Proxies S3 (LocalStack) requests through the Vite dev server
      // to avoid CORS issues when SSH port-forwarding only the frontend port.
      '/s3-proxy/echoroo': {
        target: process.env.S3_PROXY_TARGET || 'http://localstack:4566',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/s3-proxy/, ''),
        // Allow large file uploads (up to 2 GB) without timeout
        timeout: 600000,       // 10 minutes for the proxy connection
        proxyTimeout: 600000,  // 10 minutes for the target response
      }
    }
  }
});

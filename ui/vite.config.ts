import { fileURLToPath } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import { tanstackRouter } from '@tanstack/router-plugin/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'

// The FastAPI server the dev server proxies to: `npm run dev:api` starts it with mock data.
const api = process.env.CANOPY_API ?? 'http://127.0.0.1:8765'

// Fonts to preload: the latin subset of each self-hosted family. Others load on demand by unicode-range.
const PRELOAD_FONTS = /^ibm-plex-(sans-latin-wght|mono-latin-(400|500|600))-normal-.*\.woff2$/

/** Adds a <link rel="preload"> for each font PRELOAD_FONTS matches, so text never paints in a fallback face. */
function preloadFonts(): Plugin {
    return {
        name: 'canopy:preload-fonts',
        apply: 'build',
        transformIndexHtml(_html, ctx) {
            const fonts = Object.keys(ctx.bundle ?? {}).filter((file) =>
                PRELOAD_FONTS.test(file.split('/').pop() ?? ''),
            )
            return fonts.map((file) => ({
                tag: 'link',
                attrs: { rel: 'preload', as: 'font', type: 'font/woff2', href: `./${file}`, crossorigin: '' },
                injectTo: 'head',
            }))
        },
    }
}

/** The SPA's build and dev server: file-based routes, the React Compiler, Tailwind, and `/api` proxied in dev. */
export default defineConfig({
    // Relative URLs: FastAPI writes a <base href> into index.html, so one build serves under any path prefix.
    base: './',
    plugins: [
        // Before react(): it generates src/routeTree.gen.ts from src/routes/.
        tanstackRouter({ target: 'react', autoCodeSplitting: true }),
        react({ compiler: true }),
        tailwindcss(),
        preloadFonts(),
    ],
    resolve: {
        alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
    },
    server: {
        host: '127.0.0.1',
        port: 5173,
        strictPort: true,
        // /api includes the SSE stream; the proxy streams it as it arrives.
        proxy: { '/api': { target: api, changeOrigin: true } },
    },
    build: {
        outDir: 'dist',
        emptyOutDir: true,
        assetsDir: 'assets',
        // Fonts stay files, never inlined data: URLs, so they cache and preload.
        assetsInlineLimit: 0,
    },
})

import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import { tanstackRouter } from '@tanstack/router-plugin/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import type { Plugin } from 'vite'

// The FastAPI server the dev server proxies to: `npm run dev:api` starts it with mock data.
const api = process.env.CANOPY_API ?? 'http://127.0.0.1:8765'

// Fonts to preload: the latin subset of each self-hosted family. Others load on demand by unicode-range.
const PRELOAD_FONTS = /^ibm-plex-(sans-latin-wght|mono-latin-(400|500|600))-normal-.*\.woff2$/u

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

// Swagger UI's script and stylesheet, for the API's docs page FastAPI serves at /api/docs. Copied into the build's
// api-docs/, so that page loads nothing from another origin.
const SWAGGER_UI = new URL('./node_modules/swagger-ui-dist/', import.meta.url)
const SWAGGER_UI_FILES = ['swagger-ui-bundle.js', 'swagger-ui.css']

/** Copies SWAGGER_UI_FILES into the build's api-docs/, where the server serves them as it does any built file. */
function apiDocs(): Plugin {
    return {
        name: 'canopy:api-docs',
        apply: 'build',
        async generateBundle() {
            const files = await Promise.all(
                SWAGGER_UI_FILES.map(async (name) => ({ name, source: await readFile(new URL(name, SWAGGER_UI)) })),
            )
            for (const { name, source } of files) {
                this.emitFile({ type: 'asset', fileName: `api-docs/${name}`, source })
            }
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
        apiDocs(),
    ],
    resolve: {
        alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
    },
    server: {
        host: '127.0.0.1',
        port: 5173,
        strictPort: true,
        // /api includes the SSE stream, which the proxy streams as it arrives, and /api-docs, the docs page's files.
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

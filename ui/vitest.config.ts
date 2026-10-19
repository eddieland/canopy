import { fileURLToPath } from 'node:url'

import react from '@vitejs/plugin-react'
import { searchForWorkspaceRoot } from 'vite'
import { defineConfig } from 'vitest/config'

/**
 * Unit tests: every `*.test.ts(x)` under src, in happy-dom, with the app's `@` alias. COVERAGE=1 (`make check
 * COVERAGE=1`) also measures coverage and writes coverage/lcov.info, with paths from the repository root, which is how
 * CI feeds Codecov.
 */
export default defineConfig({
    plugins: [react({ compiler: true })],
    resolve: {
        alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
    },
    // The guide shows the repository's example config files whole (src/lib/guide.ts), from outside ui/.
    server: {
        fs: { allow: [searchForWorkspaceRoot(process.cwd()), fileURLToPath(new URL('../examples', import.meta.url))] },
    },
    test: {
        environment: 'happy-dom',
        include: ['src/**/*.test.{ts,tsx}'],
        restoreMocks: true,
        unstubGlobals: true,
        coverage: {
            enabled: process.env['COVERAGE'] === '1',
            provider: 'v8',
            include: ['src/**/*.{ts,tsx}'],
            exclude: ['src/**/*.test.{ts,tsx}', 'src/**/*.gen.ts', 'src/test-utils.ts', 'src/api/mocks.ts'],
            reporter: ['text-summary', ['lcovonly', { projectRoot: '..' }]],
        },
    },
})

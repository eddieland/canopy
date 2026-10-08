import { fileURLToPath } from 'node:url'

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
    plugins: [react({ compiler: true })],
    resolve: {
        alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
    },
    test: {
        environment: 'happy-dom',
        include: ['src/**/*.test.{ts,tsx}'],
        restoreMocks: true,
        unstubGlobals: true,
    },
})

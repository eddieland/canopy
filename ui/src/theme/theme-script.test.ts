import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { beforeEach, describe, expect, it } from 'vitest'

import { stubSystemTheme } from '@/test-utils'

import { STORAGE_KEY as PALETTE_KEY } from './palette'
import { STORAGE_KEY } from './store'

// The blocking script in index.html, run exactly as written.
const html = readFileSync(resolve(import.meta.dirname, '../../index.html'), 'utf8')
const script = /<script>([\s\S]*?)<\/script>/u.exec(html)?.[1]
if (!script) {
    throw new Error('index.html has no inline theme script')
}
// The test is of that script's own text, so it runs from its source.
// oxlint-disable-next-line typescript/no-implied-eval
const run = new Function(script) as () => void

beforeEach(() => {
    localStorage.clear()
    document.documentElement.className = ''
    document.documentElement.removeAttribute('style')
    delete document.documentElement.dataset.lightPalette
    delete document.documentElement.dataset.darkPalette
})

describe('index.html theme script', () => {
    it('uses the same storage keys as the stores', () => {
        expect(script).toContain(`'${STORAGE_KEY}'`)
        expect(script).toContain(`'${PALETTE_KEY}'`)
    })

    it.each([
        { stored: 'dark', system: false, dark: true },
        { stored: 'light', system: true, dark: false },
        { stored: null, system: true, dark: true },
        { stored: null, system: false, dark: false },
        { stored: 'garbage', system: true, dark: true },
    ])('stored $stored with a dark system $system: dark is $dark', ({ stored, system, dark }) => {
        stubSystemTheme(system)
        if (stored) {
            localStorage.setItem(STORAGE_KEY, stored)
        }
        run()
        expect(document.documentElement.classList.contains('dark')).toBe(dark)
        expect(document.documentElement.style.colorScheme).toBe(dark ? 'dark' : 'light')
    })

    it.each([
        { stored: null, light: 'lavender', dark: 'indigo' },
        { stored: '{"dark":"grey"}', light: 'lavender', dark: 'grey' },
        { stored: '{"light":"off-white","dark":"grey"}', light: 'off-white', dark: 'grey' },
        { stored: '{"light":"solarized"}', light: 'solarized', dark: 'indigo' },
        { stored: '{"light":"grey","dark":"solarized"}', light: 'lavender', dark: 'indigo' },
        { stored: 'not json', light: 'lavender', dark: 'indigo' },
    ])('stored palettes $stored: light wears $light, dark $dark', ({ stored, light, dark }) => {
        stubSystemTheme(false)
        if (stored) {
            localStorage.setItem(PALETTE_KEY, stored)
        }
        run()
        expect(document.documentElement.dataset.lightPalette).toBe(light)
        expect(document.documentElement.dataset.darkPalette).toBe(dark)
    })
})

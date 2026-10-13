import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { beforeEach, describe, expect, it } from 'vitest'

import { stubSystemTheme } from '@/test-utils'

import { STORAGE_KEY } from './store'

// The blocking script in index.html, run exactly as written.
const html = readFileSync(resolve(import.meta.dirname, '../../index.html'), 'utf8')
const script = /<script>([\s\S]*?)<\/script>/u.exec(html)?.[1]
if (!script) {
    throw new Error('index.html has no inline theme script')
}
const run = new Function(script) as () => void

beforeEach(() => {
    localStorage.clear()
    document.documentElement.className = ''
    document.documentElement.removeAttribute('style')
})

describe('index.html theme script', () => {
    it('uses the same storage key as the store', () => {
        expect(script).toContain(`'${STORAGE_KEY}'`)
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
})

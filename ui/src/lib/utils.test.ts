import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

import { cn, isBlank } from './utils'

const tokens = readFileSync(resolve(import.meta.dirname, '../styles/tokens.css'), 'utf8')

/** The names the stylesheet's theme gives under `--{namespace}-*`, without their `--x--line-height` parts. */
function themeNames(namespace: string): string[] {
    const pattern = new RegExp(String.raw`^\s*--${namespace}-([\w-]+?)\s*:`, 'gmu')
    return [...tokens.matchAll(pattern)].map(([, name]) => name ?? '').filter((name) => !name.includes('--'))
}

describe('cn', () => {
    it('lets a later utility override an earlier one of the same kind', () => {
        expect(cn('px-2 text-sm', 'px-3')).toBe('text-sm px-3')
    })

    it.each(themeNames('text'))('reads text-%s as a size, not a color', (name) => {
        expect(cn(`text-${name}`, 'text-muted-foreground')).toBe(`text-${name} text-muted-foreground`)
        expect(cn(`text-${name}`, 'text-sm')).toBe('text-sm')
    })

    it.each(themeNames('shadow'))('reads shadow-%s as a shadow, not a color', (name) => {
        expect(cn(`shadow-${name}`, 'shadow-accent')).toBe(`shadow-${name} shadow-accent`)
        expect(cn(`shadow-${name}`, 'shadow-none')).toBe('shadow-none')
    })
})

describe('isBlank', () => {
    it('is true for what React renders as nothing, and false for anything it shows', () => {
        for (const node of [null, undefined, false, true, '']) {
            expect(isBlank(node)).toBe(true)
        }
        for (const node of ['text', 0, ['a']]) {
            expect(isBlank(node)).toBe(false)
        }
    })
})

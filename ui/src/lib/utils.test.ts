import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

import { cn, isBlank } from './utils'

const tokens = readFileSync(resolve(import.meta.dirname, '../styles/tokens.css'), 'utf8')

/** The utilities the stylesheet's theme makes from `--{namespace}-*`, without their `--x--line-height` parts. */
function themeClasses(namespace: string): string[] {
    const pattern = new RegExp(String.raw`^\s*--${namespace}-([\w-]+?)\s*:`, 'gmu')
    return [...tokens.matchAll(pattern)]
        .map(([, name]) => name ?? '')
        .filter((name) => !name.includes('--'))
        .map((name) => `${namespace}-${name}`)
}

describe('cn', () => {
    it('lets a later utility override an earlier one of the same kind', () => {
        expect(cn('px-2 text-sm', 'px-3')).toBe('text-sm px-3')
    })

    it.each(themeClasses('text'))('reads %s as a size, not a color', (size) => {
        expect(cn(size, 'text-muted-foreground')).toBe(`${size} text-muted-foreground`)
        expect(cn(size, 'text-sm')).toBe('text-sm')
    })

    it.each(themeClasses('shadow'))('reads %s as a shadow, not a color', (shadow) => {
        expect(cn(shadow, 'shadow-accent')).toBe(`${shadow} shadow-accent`)
        expect(cn(shadow, 'shadow-none')).toBe('shadow-none')
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

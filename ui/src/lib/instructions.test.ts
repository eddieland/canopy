import { describe, expect, it } from 'vitest'

import { savedBytes } from './instructions'

describe('savedBytes', () => {
    it('counts UTF-8 bytes, as a run does, not characters', () => {
        expect(savedBytes('…\n')).toBe(4)
    })

    it('counts the newline a save adds to a last line left open', () => {
        expect(savedBytes('Run the linters.')).toBe(17)
        expect(savedBytes('Run the linters.\n')).toBe(17)
    })

    it('adds nothing to empty text, which a save leaves empty', () => {
        expect(savedBytes('')).toBe(0)
    })
})

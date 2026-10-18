import { describe, expect, it } from 'vitest'

import { foldWords, grouped } from './fold'

describe('foldWords', () => {
    it('says how many a fold holds, one or many, and how many of them its step draws past one', () => {
        expect(foldWords(1, 500, ['hidden line', 'hidden lines'])).toBe('Show 1 hidden line')
        expect(foldWords(500, 500, ['more row', 'more rows'])).toBe('Show 500 more rows')
        expect(foldWords(13_029, 500, ['hidden line', 'hidden lines'])).toBe('Show 500 of 13,029 hidden lines')
    })
})

describe('grouped', () => {
    it('groups a count by thousands, whatever the locale', () => {
        expect(grouped(999)).toBe('999')
        expect(grouped(1_234_567)).toBe('1,234,567')
    })
})

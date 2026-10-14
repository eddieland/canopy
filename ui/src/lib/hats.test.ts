import { describe, expect, it } from 'vitest'

import { balanceCents, buy, EMPTY, HATS, parseWardrobe } from './hats'

describe('HATS', () => {
    it('is cheapest first, each hat once', () => {
        const prices = HATS.map((h) => h.price)
        expect(prices).toEqual(prices.toSorted((a, b) => a - b))
        expect(new Set(HATS.map((h) => h.id)).size).toBe(HATS.length)
    })
})

describe('parseWardrobe', () => {
    it('is empty for anything it cannot read', () => {
        expect(parseWardrobe(null)).toEqual(EMPTY)
        expect(parseWardrobe('not json')).toEqual(EMPTY)
        expect(parseWardrobe('3')).toEqual(EMPTY)
    })

    it('keeps the known hats, once each, in shop order, and the worn one only if owned', () => {
        const raw = JSON.stringify({ owned: ['top', 'fedora', 'party', 'party'], worn: 'top' })
        expect(parseWardrobe(raw)).toEqual({ owned: ['party', 'top'], worn: 'top' })
        expect(parseWardrobe(JSON.stringify({ owned: ['party'], worn: 'crown' }))).toEqual({
            owned: ['party'],
            worn: null,
        })
    })
})

describe('balanceCents', () => {
    it('is the lifetime spend less every hat bought, never below zero', () => {
        expect(balanceCents(9.23, [])).toBe(923)
        expect(balanceCents(9.23, ['party', 'beanie'])).toBe(323)
        expect(balanceCents(0.5, ['party'])).toBe(0)
        expect(balanceCents(null, [])).toBe(0)
        expect(balanceCents(undefined, [])).toBe(0)
    })

    it('counts in cents, so a float sum does not cost a hat', () => {
        expect(balanceCents(0.1 + 0.2 + 0.7, [])).toBe(100)
        expect(buy(EMPTY, 'party', 0.1 + 0.2 + 0.7)).toBeDefined()
    })
})

describe('buy', () => {
    it('adds the hat in shop order and puts it on', () => {
        const first = buy(EMPTY, 'beanie', 9.23)
        expect(first).toEqual({ owned: ['beanie'], worn: 'beanie' })
        expect(first && buy(first, 'party', 9.23)).toEqual({ owned: ['party', 'beanie'], worn: 'party' })
    })

    it('refuses a hat the wallet cannot pay for, or one already owned', () => {
        expect(buy(EMPTY, 'propeller', 9.23)).toBeUndefined()
        expect(buy({ owned: ['beanie'], worn: null }, 'party', 5.5)).toBeUndefined()
        expect(buy({ owned: ['party'], worn: null }, 'party', 100)).toBeUndefined()
    })
})

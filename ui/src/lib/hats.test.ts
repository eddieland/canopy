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
        expect(balanceCents(400.25, [])).toBe(40_025)
        expect(balanceCents(400.25, ['party', 'beanie'])).toBe(10_025)
        expect(balanceCents(49.99, ['party'])).toBe(0)
        expect(balanceCents(null, [])).toBe(0)
        expect(balanceCents(undefined, [])).toBe(0)
    })

    it('counts in cents, so a float sum does not cost a hat', () => {
        expect(balanceCents(10.1 + 20.2 + 19.7, [])).toBe(5000)
        expect(buy(EMPTY, 'party', 10.1 + 20.2 + 19.7)).toBeDefined()
    })
})

describe('buy', () => {
    it('adds the hat in shop order and puts it on', () => {
        const first = buy(EMPTY, 'beanie', 400)
        expect(first).toEqual({ owned: ['beanie'], worn: 'beanie' })
        expect(first && buy(first, 'party', 400)).toEqual({ owned: ['party', 'beanie'], worn: 'party' })
    })

    it('refuses a hat the wallet cannot pay for, or one already owned', () => {
        expect(buy(EMPTY, 'propeller', 400)).toBeUndefined()
        expect(buy({ owned: ['beanie'], worn: null }, 'party', 299.99)).toBeUndefined()
        expect(buy({ owned: ['party'], worn: null }, 'party', 10_000)).toBeUndefined()
    })
})

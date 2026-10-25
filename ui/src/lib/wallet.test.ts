import { describe, expect, it } from 'vitest'

import { buy, hatsCents } from './hats'
import { shellsCents } from './shells'
import { balanceCents } from './wallet'

describe('balanceCents', () => {
    it('is the lifetime spend less what the shops sold, never below zero', () => {
        expect(balanceCents(400.25, 0)).toBe(40_025)
        expect(balanceCents(400.25, hatsCents(['party', 'beanie']))).toBe(10_025)
        expect(balanceCents(400.25, hatsCents(['party']) + shellsCents(['generalist', 'sprig']))).toBe(25_025)
        expect(balanceCents(49.99, hatsCents(['party']))).toBe(0)
        expect(balanceCents(null, 0)).toBe(0)
        expect(balanceCents(undefined, 0)).toBe(0)
    })

    it('counts in cents, so a float sum does not cost a hat', () => {
        expect(balanceCents(10.1 + 20.2 + 19.7, 0)).toBe(5000)
        expect(buy({ owned: [], worn: null }, 'party', balanceCents(10.1 + 20.2 + 19.7, 0))).toBeDefined()
    })
})

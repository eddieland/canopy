import { describe, expect, it } from 'vitest'

import { DEFAULT, parseBuddy, sectionOf, TIPS, tipFor } from './buddy'

const DAY = 86_400_000

describe('parseBuddy', () => {
    it('is off unless turned on', () => {
        expect(DEFAULT).toBe('off')
        expect(parseBuddy(null)).toBe('off')
        expect(parseBuddy('on')).toBe('on')
        expect(parseBuddy('off')).toBe('off')
        expect(parseBuddy('maybe')).toBe('off')
    })
})

describe('sectionOf', () => {
    it('names the page by the first part of its path it knows', () => {
        expect(sectionOf('/attention')).toBe('attention')
        expect(sectionOf('/tickets/ABC-102')).toBe('tickets')
        expect(sectionOf('/canopy/ticks/2')).toBe('ticks')
        expect(sectionOf('/')).toBeUndefined()
        expect(sectionOf('/nowhere')).toBeUndefined()
    })
})

describe('tipFor', () => {
    it("draws from the page's tips and the ones for anywhere", () => {
        const tips = new Set(Array.from({ length: 20 }, (_, n) => tipFor('/chores/deps', n, 0)))
        expect(tips).toEqual(new Set([...TIPS.chores, ...TIPS.anywhere]))
    })

    it('draws only from the ones for anywhere on a page it does not know', () => {
        expect(TIPS.anywhere).toContain(tipFor('/nowhere', 0, 0))
    })

    it('is the same for the same page, count, and day, and moves on with either', () => {
        expect(tipFor('/runs', 1, 5 * DAY)).toBe(tipFor('/runs', 1, 5 * DAY + 1000))
        expect(tipFor('/runs', 1, 5 * DAY)).not.toBe(tipFor('/runs', 2, 5 * DAY))
        expect(tipFor('/runs', 1, 5 * DAY)).toBe(tipFor('/runs', 0, 6 * DAY))
    })
})

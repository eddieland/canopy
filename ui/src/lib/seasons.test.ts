import { describe, expect, it } from 'vitest'

import { SEASONS, seasonOn } from '@/lib/seasons'

// A local date, as the browser's calendar reads it.
function on(month: number, day: number): Date {
    return new Date(2026, month - 1, day, 12)
}

describe('seasonOn', () => {
    it("puts a jack-o'-lantern out for the second half of October", () => {
        expect(seasonOn(on(10, 14))).toBeNull()
        expect(seasonOn(on(10, 15))).toBe('halloween')
        expect(seasonOn(on(10, 30))).toBe('halloween')
        expect(seasonOn(on(10, 31))).toBe('halloween')
        expect(seasonOn(on(11, 1))).toBeNull()
    })

    it('decorates for each season on its first and last day, and not the days around it', () => {
        for (const season of SEASONS) {
            const [fromMonth, fromDay] = season.from
            const [toMonth, toDay] = season.to
            expect(seasonOn(on(fromMonth, fromDay))).toBe(season.id)
            expect(seasonOn(on(toMonth, toDay))).toBe(season.id)
            expect(seasonOn(on(fromMonth, fromDay - 1))).not.toBe(season.id)
            expect(seasonOn(on(toMonth, toDay + 1))).not.toBe(season.id)
        }
    })

    it('leaves an ordinary day bare', () => {
        expect(seasonOn(on(10, 8))).toBeNull()
        expect(seasonOn(on(7, 4))).toBeNull()
    })
})

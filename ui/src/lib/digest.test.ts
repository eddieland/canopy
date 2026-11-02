import { describe, expect, it } from 'vitest'

import { startOfDay, todayLine } from './digest'

describe('startOfDay', () => {
    it('is the local midnight of the day, however late in it', () => {
        const start = new Date(startOfDay(new Date(2026, 9, 8, 23, 59, 30).getTime()))
        expect(start.getTime()).toBe(new Date(2026, 9, 8).getTime())
    })

    it('moves on at midnight', () => {
        const before = startOfDay(new Date(2026, 9, 8, 23, 59, 59).getTime())
        const after = startOfDay(new Date(2026, 9, 9, 0, 0, 1).getTime())
        expect(after).not.toBe(before)
    })
})

describe('todayLine', () => {
    it('says what the day held', () => {
        expect(todayLine({ prs_opened: 2, ended: 5 })).toBe('Today: 2 PRs opened · 5 runs ended')
    })

    it('counts one in the singular', () => {
        expect(todayLine({ prs_opened: 1, ended: 1 })).toBe('Today: 1 PR opened · 1 run ended')
    })

    it('hides a zero rather than print it', () => {
        expect(todayLine({ prs_opened: 0, ended: 5 })).toBe('Today: 5 runs ended')
        expect(todayLine({ prs_opened: 2, ended: 0 })).toBe('Today: 2 PRs opened')
    })

    it('has no line for a day that held nothing', () => {
        expect(todayLine({ prs_opened: 0, ended: 0 })).toBeNull()
    })
})

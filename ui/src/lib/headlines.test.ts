import { describe, expect, it } from 'vitest'

import { HEADLINES, headlinesFor } from './headlines'

describe('headlinesFor', () => {
    const day = 86_400_000
    const now = Date.parse('2026-10-08T12:30:00Z')

    it('lists every headline once', () => {
        expect([...headlinesFor(now)].toSorted()).toEqual([...HEADLINES].toSorted())
    })

    it('keeps one lead all day and moves to the next one the day after', () => {
        const lead = headlinesFor(now)[0]
        const start = Math.floor(now / day) * day
        expect(headlinesFor(start)[0]).toBe(lead)
        expect(headlinesFor(start + day - 1)[0]).toBe(lead)
        expect(headlinesFor(start + day)[0]).toBe(headlinesFor(now)[1])
    })

    it('has no two headlines alike, since each is its own key', () => {
        expect(new Set(HEADLINES).size).toBe(HEADLINES.length)
    })
})

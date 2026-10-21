import { describe, expect, it } from 'vitest'

import { durationText, minutesSetFor, minutesUntil } from './notice-time'

describe('notice time', () => {
    it('says how long a notice was set for, within the bound the server holds it to', () => {
        expect(minutesSetFor('2026-10-08T11:00:00Z', '2026-10-08T15:00:00Z')).toBe(240)
        expect(minutesSetFor('2026-10-08T11:00:00Z', '2026-10-08T11:00:10Z')).toBe(1)
        expect(minutesSetFor('2026-10-01T00:00:00Z', '2026-10-09T00:00:00Z')).toBe(7 * 24 * 60)
    })

    it('rounds the time left up, so a kept notice ends no sooner than it would have', () => {
        const now = Date.parse('2026-10-08T12:00:00Z')
        expect(minutesUntil('2026-10-08T15:00:00Z', now)).toBe(180)
        expect(minutesUntil('2026-10-08T12:00:01Z', now)).toBe(1)
        expect(minutesUntil('2026-10-08T11:00:00Z', now)).toBe(1)
    })

    it("writes a duration as the CLI's --for does", () => {
        expect(durationText(240)).toBe('4h')
        expect(durationText(90)).toBe('1h30m')
        expect(durationText(1440)).toBe('1d')
        expect(durationText(1501)).toBe('1d1h1m')
    })
})

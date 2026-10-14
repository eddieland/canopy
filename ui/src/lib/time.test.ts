import { describe, expect, it } from 'vitest'

import { age, stamp } from './time'

describe('age', () => {
    const now = Date.parse('2026-10-08T12:30:00Z')

    it('names the largest whole unit, as the CLI does', () => {
        expect(age('2026-10-08T12:29:20Z', now)).toBe('40s')
        expect(age('2026-10-08T12:25:00Z', now)).toBe('5m')
        expect(age('2026-10-08T10:00:00Z', now)).toBe('2h')
        expect(age('2026-10-05T12:00:00Z', now)).toBe('3d')
    })

    it('never goes negative for a time a little ahead of the clock', () => {
        expect(age('2026-10-08T12:31:00Z', now)).toBe('0s')
    })
})

describe('stamp', () => {
    it('is the local month, day, and 24-hour time, without the year or seconds', () => {
        const iso = '2026-10-08T10:30:45Z'
        const local = new Date(iso)
        const hh = String(local.getHours()).padStart(2, '0')
        const mm = String(local.getMinutes()).padStart(2, '0')
        expect(stamp(iso)).toMatch(new RegExp(`^\\S+ ${local.getDate()} ${hh}:${mm}$`, 'u'))
    })
})

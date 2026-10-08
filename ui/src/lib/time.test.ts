import { describe, expect, it } from 'vitest'

import { age } from './time'

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

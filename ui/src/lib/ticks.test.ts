import { describe, expect, it } from 'vitest'

import { tickId } from './ticks'

describe('tickId', () => {
    it('reads a positive whole number and nothing else', () => {
        expect(tickId('12')).toBe(12)
        expect(tickId('0')).toBeNull()
        expect(tickId('012')).toBeNull()
        expect(tickId('-3')).toBeNull()
        expect(tickId('1e3')).toBeNull()
        expect(tickId('two')).toBeNull()
    })
})

import { describe, expect, it } from 'vitest'

import { byteSize, tickId, tickState } from './ticks'

describe('tickState', () => {
    it("reads a tick's ok and skipped as a run's done, and anything else that ended as failed", () => {
        expect(tickState('running')).toBe('running')
        expect(tickState('ok')).toBe('done')
        expect(tickState('skipped')).toBe('done')
        expect(tickState('overseer_failed')).toBe('failed')
        expect(tickState('abandoned')).toBe('failed')
        expect(tickState('a status added later')).toBe('failed')
    })
})

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

describe('byteSize', () => {
    it('says bytes, then KiB and MiB to one decimal', () => {
        expect(byteSize(0)).toBe('0 B')
        expect(byteSize(1023)).toBe('1023 B')
        expect(byteSize(1644)).toBe('1.6 KiB')
        expect(byteSize(1024 * 1024)).toBe('1.0 MiB')
        expect(byteSize(40 * 1024 * 1024 + 1)).toBe('40.0 MiB')
    })
})

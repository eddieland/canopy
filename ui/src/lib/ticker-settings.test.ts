import { describe, expect, it } from 'vitest'

import { clampGap, DEFAULTS, MAX_GAP, parseSettings } from './ticker-settings'

describe('parseSettings', () => {
    it('defaults to a normal speed and no gap when nothing is stored', () => {
        expect(parseSettings(null)).toEqual(DEFAULTS)
        expect(DEFAULTS).toEqual({ speed: 'normal', gap: 0 })
    })

    it('reads what was stored', () => {
        expect(parseSettings('{"speed":"spicy","gap":5}')).toEqual({ speed: 'spicy', gap: 5 })
        expect(parseSettings('{"speed":"off","gap":0}')).toEqual({ speed: 'off', gap: 0 })
    })

    it('falls back field by field on anything it does not recognize', () => {
        expect(parseSettings('not json')).toEqual(DEFAULTS)
        expect(parseSettings('[]')).toEqual(DEFAULTS)
        expect(parseSettings('{"speed":"ludicrous","gap":3}')).toEqual({ speed: 'normal', gap: 3 })
        expect(parseSettings('{"speed":"slow","gap":"3"}')).toEqual({ speed: 'slow', gap: 0 })
    })
})

describe('clampGap', () => {
    it('keeps whole seconds from 0 to the maximum', () => {
        expect(clampGap(2.4)).toBe(2)
        expect(clampGap(-5)).toBe(0)
        expect(clampGap(MAX_GAP + 1)).toBe(MAX_GAP)
    })

    it('refuses what is not a number', () => {
        expect(clampGap(Number.NaN)).toBeUndefined()
        expect(clampGap(Number.POSITIVE_INFINITY)).toBeUndefined()
        expect(clampGap('3')).toBeUndefined()
    })
})

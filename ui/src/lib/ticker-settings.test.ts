import { describe, expect, it } from 'vitest'

import { clampGap, DEFAULTS, MAX_GAP, parseSettings, parseTopics, withTopic } from './ticker-settings'

describe('parseSettings', () => {
    it('defaults to a normal speed, no gap, and every topic when nothing is stored', () => {
        expect(parseSettings(null)).toEqual(DEFAULTS)
        expect(DEFAULTS).toEqual({ speed: 'normal', gap: 0, hidden: [] })
    })

    it('reads what was stored', () => {
        expect(parseSettings('{"speed":"spicy","gap":5,"hidden":["tips"]}')).toEqual({
            speed: 'spicy',
            gap: 5,
            hidden: ['tips'],
        })
        expect(parseSettings('{"speed":"off","gap":0}')).toEqual({ speed: 'off', gap: 0, hidden: [] })
    })

    it('falls back field by field on anything it does not recognize', () => {
        expect(parseSettings('not json')).toEqual(DEFAULTS)
        expect(parseSettings('[]')).toEqual(DEFAULTS)
        expect(parseSettings('{"speed":"ludicrous","gap":3}')).toEqual({ speed: 'normal', gap: 3, hidden: [] })
        expect(parseSettings('{"speed":"slow","gap":"3"}')).toEqual({ speed: 'slow', gap: 0, hidden: [] })
        expect(parseSettings('{"hidden":"tips"}')).toEqual(DEFAULTS)
    })
})

describe('parseTopics', () => {
    it('keeps the known topics once each, in their order, and drops the rest', () => {
        expect(parseTopics(['tips', 'programming', 'tips', 'gossip', 3])).toEqual(['programming', 'tips'])
        expect(parseTopics(null)).toEqual([])
    })
})

describe('withTopic', () => {
    it('hides or shows one topic and leaves the others as they were', () => {
        expect(withTopic([], 'tips', false)).toEqual(['tips'])
        expect(withTopic(['tips'], 'programming', false)).toEqual(['programming', 'tips'])
        expect(withTopic(['programming', 'tips'], 'tips', true)).toEqual(['programming'])
        expect(withTopic(['vibes'], 'vibes', false)).toEqual(['vibes'])
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

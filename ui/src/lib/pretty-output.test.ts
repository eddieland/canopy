import { describe, expect, it } from 'vitest'

import { MAX_KEPT, parsePretty, withPretty } from './pretty-output'

describe('parsePretty', () => {
    it('reads the ticks stored, and nothing when nothing is', () => {
        expect(parsePretty('[2,7]')).toEqual([2, 7])
        expect(parsePretty(null)).toEqual([])
    })

    it('keeps only whole positive numbers, and reads anything else as none', () => {
        expect(parsePretty('[2,"3",-1,0,1.5,null,9]')).toEqual([2, 9])
        expect(parsePretty('{"2":true}')).toEqual([])
        expect(parsePretty('not json')).toEqual([])
    })
})

describe('withPretty', () => {
    it("turns one tick's on or off and leaves the others as they were", () => {
        expect(withPretty([2], 7, true)).toBe('[2,7]')
        expect(withPretty([2, 7], 2, false)).toBe('[7]')
        expect(withPretty([2], 9, false)).toBe('[2]')
    })

    it('moves a tick turned on again to the end, and drops the oldest past the limit', () => {
        expect(withPretty([2, 7], 2, true)).toBe('[7,2]')
        const full = Array.from({ length: MAX_KEPT }, (_, i) => i + 1)
        const kept = JSON.parse(withPretty(full, 1000, true)) as number[]
        expect(kept).toHaveLength(MAX_KEPT)
        expect(kept[0]).toBe(2)
        expect(kept.at(-1)).toBe(1000)
    })
})

import { describe, expect, it } from 'vitest'

import { MAX_FOLDED, parseProcessSettings, withFold } from './process-settings'

describe('parseProcessSettings', () => {
    it('reads the tree as it was left, and the busy ones by the processors when nothing is stored', () => {
        expect(parseProcessSettings('{"all":true,"order":"memory","folded":[7,9]}')).toEqual({
            all: true,
            order: 'memory',
            folded: [7, 9],
        })
        expect(parseProcessSettings(null)).toEqual({ all: false, order: 'cpu', folded: [] })
    })

    it('reads each setting alone, so one stored otherwise is its default and the rest stand', () => {
        expect(parseProcessSettings('{"all":"yes","order":"name","folded":[7,"8",-1,0,2.5]}')).toEqual({
            all: false,
            order: 'cpu',
            folded: [7],
        })
        expect(parseProcessSettings('[1]').folded).toEqual([])
        expect(parseProcessSettings('not json').all).toBe(false)
    })
})

describe('withFold', () => {
    it('folds or unfolds one process, and lets go of the oldest fold past the limit', () => {
        expect(withFold([7], 9, true)).toEqual([7, 9])
        expect(withFold([7, 9], 7, false)).toEqual([9])
        const full = Array.from({ length: MAX_FOLDED }, (_, i) => i + 1)
        const kept = withFold(full, 1000, true)
        expect(kept).toHaveLength(MAX_FOLDED)
        expect(kept[0]).toBe(2)
    })
})

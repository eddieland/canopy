import { describe, expect, it } from 'vitest'

import { axisNames, axisStep, peakIndex } from './chart'

function named(count: number, step: number): number[] {
    return Array.from({ length: count }, (_, i) => i).filter((i) => axisNames(i, count, step))
}

describe('chart', () => {
    it('finds the peak, the latest of equals, so its value is said over its bar; none where all are 0', () => {
        expect(peakIndex([2, 4.5, 1])).toBe(1)
        expect(peakIndex([3, 3])).toBe(1)
        expect(peakIndex([0, 0])).toBe(-1)
        expect(peakIndex([])).toBe(-1)
    })

    it('names every mark of a short axis, and every fifth of a long one back from the last', () => {
        expect(axisStep(7, 7)).toBe(1)
        expect(named(7, axisStep(7, 7))).toEqual([0, 1, 2, 3, 4, 5, 6])
        expect(axisStep(30, 7)).toBe(5)
        expect(named(30, axisStep(30, 7))).toEqual([4, 9, 14, 19, 24, 29])
        expect(named(13, axisStep(13, 12))).toEqual([2, 7, 12])
    })

    it('names fewer marks where names that often would touch, never fewer than it must', () => {
        // A week 44px a bar names each day's 48px name every second bar; 50px a bar, every bar.
        expect(axisStep(7, 7, { pitch: 44, label: 48 })).toBe(2)
        expect(axisStep(7, 7, { pitch: 50, label: 48 })).toBe(1)
        // A month 9px a bar has no room for every fifth: every tenth.
        expect(axisStep(30, 7, { pitch: 9, label: 48 })).toBe(10)
        expect(axisStep(30, 7, { pitch: 20, label: 48 })).toBe(5)
        // One bar has all the room there is.
        expect(axisStep(1, 7, { pitch: Number.POSITIVE_INFINITY, label: 48 })).toBe(1)
    })

    it('names the last mark alone when not even the coarsest step fits', () => {
        const step = axisStep(30, 7, { pitch: 0.1, label: 48 })
        expect(named(30, step)).toEqual([29])
    })
})

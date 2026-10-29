import { describe, expect, it } from 'vitest'

import type { HostHistory, HostSample } from '@/api/types'

import { areaPath, linePath, nearest, trend } from './trend'

const T0 = Date.parse('2026-10-08T12:00:00Z')

// A reading `seconds` after T0 with a load of `load`.
function sample(seconds: number, load: number | null): HostSample {
    return {
        at: new Date(T0 + seconds * 1000).toISOString(),
        load,
        memory_used: null,
        rss: null,
        disks: [],
    }
}

function history(samples: HostSample[], kept = 11, every = 10): HostHistory {
    return { every_seconds: every, kept, samples }
}

describe('trend', () => {
    it('is nothing until there is a reading of the measure', () => {
        expect(trend(history([]), (s) => s.load)).toBeNull()
        expect(trend(history([sample(0, null)]), (s) => s.load)).toBeNull()
    })

    it('spans as long before the latest reading as the server keeps readings, with the peak and the low', () => {
        const t = trend(history([sample(0, 1), sample(10, 3), sample(20, 2)]), (s) => s.load)
        expect(t?.end).toBe(T0 + 20_000)
        expect(t?.start).toBe(T0 + 20_000 - 100_000)
        expect([t?.peak, t?.low]).toEqual([3, 1])
    })

    it('breaks the line where the server was not reading, and where the measure read nothing', () => {
        const t = trend(
            history([sample(0, 1), sample(10, 1), sample(60, 2), sample(70, null), sample(80, 3)]),
            (s) => s.load,
        )
        expect(t?.runs.map((run) => run.map((p) => p.value))).toEqual([[1, 1], [2], [3]])
        expect(t?.points).toHaveLength(4)
    })
})

describe('the paths', () => {
    // Read every 50 seconds, three kept: the chart spans the readings exactly.
    const t = trend(history([sample(0, 0), sample(50, 2), sample(100, 4)], 3, 50), (s) => s.load)

    it('draw a line across the box from zero, and the area under it', () => {
        if (t === null) {
            throw new Error('no trend')
        }
        const [run = []] = t.runs
        expect(linePath(t, run, 4)).toBe('M0,100 L500,50 L1000,0')
        expect(areaPath(t, run, 4)).toBe('M0,100 L500,50 L1000,0 L1000,100 L0,100 Z')
    })

    it('draw a run of one reading as a dot, with no area', () => {
        const one = trend(history([sample(0, 2)]), (s) => s.load)
        if (one === null) {
            throw new Error('no trend')
        }
        const [run = []] = one.runs
        expect(linePath(one, run, 4)).toBe('M1000,50 L1000,50')
        expect(areaPath(one, run, 4)).toBe('')
    })

    it('snap the crosshair to the nearest reading', () => {
        if (t === null) {
            throw new Error('no trend')
        }
        expect(nearest(t, 0.4)?.value).toBe(2)
        expect(nearest(t, 0.9)?.value).toBe(4)
    })
})

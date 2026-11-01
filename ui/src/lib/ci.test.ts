import { describe, expect, it } from 'vitest'

import type { CiDay } from '@/api/types'
import type { Clock } from '@/lib/clock'

import {
    ciBars,
    ciDayHint,
    ciFigures,
    ciLine,
    ciSeries,
    ciWindow,
    failureRate,
    fixRateText,
    kickText,
    nextHeadText,
    nextText,
    OTHER,
} from './ci'

const H24: Clock = { hours: '24', zone: false }

function day(name: string, red: number[]): CiDay {
    return { day: name, start: `${name}T00:00:00Z`, red, heads: 0, green_first: 0 }
}

describe('ci', () => {
    it('offers the week and 30 days, as the health page does', () => {
        expect(ciWindow({ days: '30' })).toEqual({ days: 30 })
        expect(ciWindow({ days: 7 })).toEqual({ days: 7 })
        expect(ciWindow({ days: '14' })).toBeUndefined()
        expect(ciWindow({})).toBeUndefined()
    })

    it("sums the window's headline figures: heads, their share green first time, red runs, and fixes", () => {
        expect(
            ciFigures({
                heads: 4,
                green_first: 3,
                per_day: [day('2026-10-07', [2, 1]), day('2026-10-08', [1])],
                fixes: [],
            }),
        ).toEqual({ heads: 4, greenFirst: 0.75, red: 4, fixes: 0 })
        expect(ciFigures({ heads: 0, green_first: 0, per_day: [], fixes: [] }).greenFirst).toBeNull()
    })

    it("says the window's state: the heads green first time and the kicks", () => {
        expect(ciLine({ days: 7, heads: 7, green_first: 5, kicks: [] })).toBe(
            '71% of PR heads green first time · no flaky kicks over 7 days',
        )
        expect(ciLine({ days: 30, heads: 0, green_first: 0, kicks: [] })).toBe(
            'no PR head checked · no flaky kicks over 30 days',
        )
    })

    it('names the top checks by rank, each in its fill, and the rest as other in the neutral', () => {
        const series = ciSeries(['e2e', 'unit test', null])
        expect(series.map((s) => [s.key, s.label, s.fill])).toEqual([
            ['check-0', 'e2e', 'bg-check-1'],
            ['check-1', 'unit test', 'bg-check-2'],
            [OTHER, 'other', 'bg-check-other'],
        ])
    })

    it("draws each day's red runs by series, and says them on hover", () => {
        const series = ciSeries(['e2e', null])
        const [bar] = ciBars([day('2026-10-07', [2, 1])], series, H24)
        expect([bar?.key, bar?.label, bar?.total, bar?.totalText]).toEqual(['2026-10-07', 'Oct 7', 3, '3'])
        expect(bar?.segments.map((s) => [s.key, s.value])).toEqual([
            ['check-0', 2],
            [OTHER, 1],
        ])
        expect(ciDayHint(day('2026-10-07', [2, 1]), series, H24)).toBe('Oct 7: 3 red, e2e 2, other 1')
        expect(ciDayHint(day('2026-10-08', [0, 0]), series, H24)).toBe('Oct 8: 0 red')
    })

    it("says a check's failure rate among red and green, and how often a new head fixed it", () => {
        expect(failureRate({ red: 2, green: 3 })).toBe('40%')
        expect(failureRate({ red: 0, green: 0 })).toBe('–')
        expect(nextHeadText({ followed: 3, passed: 2 })).toBe('2 of 3')
        expect(nextHeadText({ followed: 0, passed: 0 })).toBe('–')
        expect(nextText('neither')).toBe('neither')
        expect(nextText(null)).toBe('not yet')
    })

    it("sums the fixes' checks that a next head judged, green out of green and red", () => {
        const checks = [
            { pr_url: 'u', name: 'a', next: 'green' as const },
            { pr_url: 'u', name: 'b', next: 'red' as const },
            { pr_url: 'u', name: 'c', next: 'neither' as const },
            { pr_url: 'u', name: 'd', next: null },
        ]
        expect(fixRateText([{ checks }])).toBe('1 of 2 checks green on the next head')
        expect(fixRateText([{ checks: checks.slice(2) }])).toBe('')
    })

    it('holds a kick against the limit, or not with kicks now off', () => {
        expect(kickText({ kick: 2 }, 3)).toBe('kick 2 of 3')
        expect(kickText({ kick: 2 }, 0)).toBe('kick 2')
    })
})

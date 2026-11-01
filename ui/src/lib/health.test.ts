import { describe, expect, it } from 'vitest'

import type { HealthCounts, HealthDay, HealthOutcome } from '@/api/types'
import type { Clock } from '@/lib/clock'

import {
    countSum,
    HEALTH_SERIES,
    healthBars,
    healthDayHint,
    healthFigures,
    healthLine,
    healthWindow,
    previousHealthFigures,
} from './health'

const H24: Clock = { hours: '24', zone: false }
const NONE: HealthCounts = { overseer: 0, workers: 0, plans: 0, chores: 0, reviews: 0, tasks: 0 }

function day(name: string, ended: Partial<HealthCounts>, failed: Partial<HealthCounts> = {}): HealthDay {
    return { day: name, start: `${name}T00:00:00Z`, ended: { ...NONE, ...ended }, failed: { ...NONE, ...failed } }
}

function outcome(failed: boolean, usd: number | null): HealthOutcome {
    return { kind: 'workers', what: 'implement', status: failed ? 'failed' : 'done', failed, runs: 1, cost_usd: usd }
}

describe('health', () => {
    it('offers the week and 30 days, as canopy health reads them', () => {
        expect(healthWindow({ days: '30' })).toEqual({ days: 30 })
        expect(healthWindow({ days: 7 })).toEqual({ days: 7 })
        expect(healthWindow({ days: '14' })).toBeUndefined()
        expect(healthWindow({})).toBeUndefined()
    })

    it("says the window's state: how many of its ended runs failed", () => {
        const week = [day('2026-10-07', { workers: 10, overseer: 2 }, { workers: 2 }), day('2026-10-08', { chores: 1 })]
        expect(healthLine({ days: 7, per_day: week })).toBe('2 of 13 runs failed over 7 days')
        expect(healthLine({ days: 30, per_day: [day('2026-10-08', {})] })).toBe('no run ended over 30 days')
        expect(healthLine({ days: 7, per_day: [day('2026-10-08', { reviews: 1 })] })).toBe(
            '0 of 1 run failed over 7 days',
        )
    })

    it("sums the window's headline figures: its runs, failures, their share, and what the failures cost", () => {
        const week = [day('2026-10-07', { workers: 8 }, { workers: 2 }), day('2026-10-08', { chores: 2 })]
        expect(
            healthFigures({ per_day: week, outcomes: [outcome(true, 1.5), outcome(true, null), outcome(false, 9)] }),
        ).toEqual({ runs: 10, failed: 2, rate: 0.2, failedUsd: 1.5 })
        expect(healthFigures({ per_day: [day('2026-10-08', {})], outcomes: [outcome(true, null)] })).toEqual({
            runs: 0,
            failed: 0,
            rate: null,
            failedUsd: null,
        })
    })

    it("reads the window before's figures as the window's, a rate only over ended runs", () => {
        const before = { since: '2026-09-25T00:00:00Z', until: '2026-10-02T00:00:00Z' }
        expect(previousHealthFigures({ ...before, runs_ended: 8, failed: 2, failed_cost_usd: 0.5 })).toEqual({
            runs: 8,
            failed: 2,
            rate: 0.25,
            failedUsd: 0.5,
        })
        expect(previousHealthFigures({ ...before, runs_ended: 0, failed: 0, failed_cost_usd: null }).rate).toBeNull()
    })

    it('says a day on hover with each kind that failed, by the legend', () => {
        expect(healthDayHint(day('2026-10-07', { overseer: 4, workers: 8 }, { overseer: 1, workers: 2 }), H24)).toBe(
            'Oct 7: 3 failed of 12 ended, overseer 1, workers 2',
        )
        expect(healthDayHint(day('2026-10-08', { tasks: 1 }), H24)).toBe('Oct 8: 0 failed of 1 ended')
    })

    it("draws each day's failed runs, by kind bottom up", () => {
        const [bar] = healthBars([day('2026-10-07', { workers: 3, reviews: 1 }, { workers: 2, reviews: 1 })], H24)
        expect([bar?.key, bar?.label, bar?.total, bar?.totalText]).toEqual(['2026-10-07', 'Oct 7', 3, '3'])
        expect(bar?.segments.map((s) => s.key)).toEqual(HEALTH_SERIES.map((s) => s.key))
        expect(bar?.segments.filter((s) => s.value > 0).map((s) => [s.key, s.value])).toEqual([
            ['workers', 2],
            ['reviews', 1],
        ])
        expect(countSum({ ...NONE, plans: 2, tasks: 1 })).toBe(3)
    })
})

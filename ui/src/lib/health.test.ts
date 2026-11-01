import { describe, expect, it } from 'vitest'

import type { HealthCounts, HealthDay, HealthDuration, HealthOutcome } from '@/api/types'
import type { Clock } from '@/lib/clock'

import {
    binsText,
    countSum,
    dayRateText,
    durationsByKind,
    HEALTH_SERIES,
    healthBars,
    healthDayHint,
    healthFigures,
    healthLine,
    healthWindow,
    minutesText,
    nearLimit,
    outcomeTree,
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

// A sort's durations, as the report lists them, one run of a minute each.
function took(kind: HealthDuration['kind'], what: string): HealthDuration {
    return {
        kind,
        what,
        runs: 1,
        median_minutes: 1,
        p90_minutes: 1,
        longest_minutes: 1,
        timeouts: 0,
        limit_minutes: 15,
        bins: null,
    }
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

    it('reads the outcomes as a tree: a kind over its sorts, each with its statuses, the most runs first', () => {
        const rows: HealthOutcome[] = [
            { kind: 'overseer', what: 'live', status: 'ok', failed: false, runs: 2, cost_usd: 0.5 },
            { kind: 'workers', what: 'implement', status: 'blocked', failed: false, runs: 1, cost_usd: 1 },
            { kind: 'workers', what: 'implement', status: 'done', failed: false, runs: 3, cost_usd: null },
            { kind: 'workers', what: 'implement', status: 'failed', failed: true, runs: 1, cost_usd: 0.25 },
            { kind: 'workers', what: 'resume', status: 'done', failed: false, runs: 1, cost_usd: null },
        ]
        const [overseer, workers] = outcomeTree(rows)
        expect(overseer).toEqual({
            kind: 'overseer',
            runs: 2,
            failed: 0,
            costUsd: 0.5,
            sorts: [{ what: 'live', runs: 2, costUsd: 0.5, statuses: [{ status: 'ok', failed: false, runs: 2 }] }],
        })
        expect([workers?.runs, workers?.failed, workers?.costUsd]).toEqual([6, 1, 1.25])
        expect(workers?.sorts.map((s) => [s.what, s.runs, s.costUsd])).toEqual([
            ['implement', 5, 1.25],
            // A cost nothing reported stays apart from a cost of nothing.
            ['resume', 1, null],
        ])
        expect(workers?.sorts[0]?.statuses.map((st) => `${st.status} ${st.runs}`)).toEqual([
            'done 3',
            'blocked 1',
            'failed 1',
        ])
    })

    it("says a day's failure rate, or a dash with nothing ended", () => {
        expect(dayRateText(day('2026-10-07', { workers: 3, reviews: 1 }, { workers: 1 }))).toBe('25%')
        expect(dayRateText(day('2026-10-08', {}))).toBe('–')
    })

    it("times a run in the readout's units, and calls a median close to its timeout", () => {
        expect([0.5, 4.25, 27.5, 90].map((m) => minutesText(m))).toEqual(['30s', '4.3m', '28m', '1.5h'])
        expect(nearLimit({ median_minutes: 34, limit_minutes: 45 })).toBe(true)
        expect(nearLimit({ median_minutes: 30, limit_minutes: 45 })).toBe(false)
        expect(nearLimit({ median_minutes: 30, limit_minutes: null })).toBe(false)
    })

    it("says a sort's spread against its timeout in words, the bands with runs alone", () => {
        const bins = { under_quarter: 2, under_half: 0, under_three_quarters: 1, under_limit: 0, over_limit: 1 }
        expect(binsText(bins)).toBe('2 under 25%, 1 at 50–75%, 1 at the limit')
    })

    it("groups the durations by kind, in the report's order", () => {
        const groups = durationsByKind([
            took('workers', 'implement'),
            took('workers', 'resume'),
            took('chores', 'deps'),
        ])
        expect(groups.map((g) => [g.kind, g.sorts.map((d) => d.what)])).toEqual([
            ['workers', ['implement', 'resume']],
            ['chores', ['deps']],
        ])
    })
})

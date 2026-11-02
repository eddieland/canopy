import { describe, expect, it } from 'vitest'

import type { SpendFirstCallWeek } from '@/api/types'

import {
    firstKind,
    KIND_SERIES,
    seriesOf,
    seriesWeeks,
    snapshotsOf,
    weekChanges,
    weekHint,
    weekLabel,
    weekStart,
} from './first-calls'

/** A week of a series, every number a plain one unless the test says otherwise. */
function week(over: Partial<SpendFirstCallWeek>): SpendFirstCallWeek {
    return {
        kind: 'workers',
        by: 'kind',
        name: null,
        week: '2026-W41',
        runs: 2,
        first_call: 24_200,
        hit_rate: 0.85,
        new_runtime_versions: [],
        new_digests: [],
        ...over,
    }
}

// The server's order: each kind's own series first, then its chores', then its models', the runs no one model served
// last; each series' weeks oldest first.
const WEEKS: SpendFirstCallWeek[] = [
    week({ kind: 'overseer' }),
    week({ week: '2026-W40' }),
    week({ week: '2026-W41', new_runtime_versions: ['1.0.104'] }),
    week({ by: 'model', name: 'anthropic/claude-sonnet-4-5', week: '2026-W40' }),
    week({ by: 'model', name: 'anthropic/claude-sonnet-4-5' }),
    week({ by: 'model', name: null }),
    week({ kind: 'chores' }),
    week({ kind: 'chores', by: 'chore', name: 'deps' }),
    week({ kind: 'chores', by: 'model', name: 'anthropic/claude-haiku-4-5' }),
]

describe('firstKind', () => {
    it('is the kind picked, else the first in canopy spend order with a week', () => {
        expect(firstKind(WEEKS, 'chores')).toBe('chores')
        expect(firstKind(WEEKS, undefined)).toBe('overseer')
        expect(firstKind(WEEKS.slice(1), undefined)).toBe('workers')
        expect(firstKind([], undefined)).toBeUndefined()
    })
})

describe('seriesOf', () => {
    it("offers the kind's runs, then each chore's and each model's, never the runs no one model served", () => {
        expect(seriesOf(WEEKS, 'workers')).toEqual([
            { id: KIND_SERIES, label: 'all runs', model: false },
            { id: 'model:anthropic/claude-sonnet-4-5', label: 'anthropic/claude-sonnet-4-5', model: true },
        ])
        expect(seriesOf(WEEKS, 'chores').map((s) => s.id)).toEqual([
            KIND_SERIES,
            'chore:deps',
            'model:anthropic/claude-haiku-4-5',
        ])
        expect(seriesOf(WEEKS, 'reviews')).toEqual([])
    })
})

describe('seriesWeeks', () => {
    it("keeps one series' weeks, oldest first, and none of a series the kind does not have", () => {
        expect(seriesWeeks(WEEKS, 'workers', KIND_SERIES).map((w) => w.week)).toEqual(['2026-W40', '2026-W41'])
        expect(seriesWeeks(WEEKS, 'workers', 'model:anthropic/claude-sonnet-4-5')).toHaveLength(2)
        expect(seriesWeeks(WEEKS, 'workers', 'chore:deps')).toEqual([])
    })
})

describe('weekStart and weekLabel', () => {
    it('name an ISO week by its Monday, across a year whose first week starts in December', () => {
        expect(weekStart('2026-W41')?.toISOString()).toBe('2026-10-05T00:00:00.000Z')
        expect(weekStart('2026-W01')?.toISOString()).toBe('2025-12-29T00:00:00.000Z')
        expect(weekStart('2020-W53')?.toISOString()).toBe('2020-12-28T00:00:00.000Z')
        expect(weekLabel('2026-W40')).toBe('Sep 28')
    })

    it('say a week they cannot read as the server named it', () => {
        expect(weekStart('2026-41')).toBeUndefined()
        expect(weekStart('2026-W00')).toBeUndefined()
        expect(weekLabel('soon')).toBe('soon')
    })
})

describe('weekChanges and weekHint', () => {
    it("name what a week's runs used first in canopy spend's words, the runtime before the snapshot", () => {
        const changed = week({ new_runtime_versions: ['1.0.104'], new_digests: ['a81d2c4e9f306b17'] })
        expect(weekChanges(changed)).toEqual(['runtime 1.0.104', 'snapshot a81d2c4e9f306b17'])
        expect(weekChanges(week({}))).toEqual([])
        expect(weekHint({ ...changed, week: '2026-W40', runs: 3, first_call: 22_400, hit_rate: 0.79 })).toBe(
            'Week of Sep 28: 79% from the cache, a median 22.4k sent, 3 runs; new runtime 1.0.104, ' +
                'snapshot a81d2c4e9f306b17',
        )
    })

    it('count a week of several new snapshots, as one change to canopy makes, and name them apart', () => {
        const several = week({ new_runtime_versions: ['1.0.104'], new_digests: ['a81d2c4e', 'b92e3d5f', 'c03f4e60'] })
        expect(weekChanges(several)).toEqual(['runtime 1.0.104', '3 snapshots'])
        expect(snapshotsOf(several)).toBe('a81d2c4e\nb92e3d5f\nc03f4e60')
        expect(snapshotsOf(week({ new_digests: ['a81d2c4e'] }))).toBeUndefined()
    })

    it('say a week whose runs recorded no cache read, and a lone run', () => {
        expect(weekHint(week({ runs: 1, hit_rate: null }))).toBe(
            'Week of Oct 5: no cache read recorded, a median 24.2k sent, 1 run',
        )
    })
})

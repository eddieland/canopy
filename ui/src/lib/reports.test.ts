import { describe, expect, it } from 'vitest'

import type { ReportMonth, ReportTicket, ReportTokens } from '@/api/types'
import { DEFAULT_CLOCK } from '@/lib/clock'
import { stamp } from '@/lib/time'

import {
    clockShare,
    hoursText,
    medianText,
    monthLabel,
    outsideHint,
    pickedMonth,
    reportLine,
    reportMonth,
    reportSpan,
    reviewWaitHint,
    sentTokens,
    toLandHint,
    wroteTokens,
} from './reports'

const TOKENS: ReportTokens = {
    input: 1000,
    output: 200,
    reasoning: 50,
    cache_read: 8000,
    cache_write: 1000,
    cache_hit: 0.8,
}

function month(name: string, cost: number | null, extra: Partial<ReportMonth> = {}): ReportMonth {
    return {
        month: name,
        since: `${name}-01T00:00:00Z`,
        until: `${name}-28T00:00:00Z`,
        runs: 0,
        cost_usd: cost,
        tokens: TOKENS,
        kinds: [],
        outside: {
            sessions: 0,
            cost_usd: null,
            tokens: { ...TOKENS, input: 0, output: 0, reasoning: 0, cache_read: 0, cache_write: 0, cache_hit: null },
        },
        models: [],
        landed: [],
        closed: 0,
        pull_requests: 0,
        per_landed_usd: null,
        median_iterations: null,
        median_pr_comments: null,
        median_hours_to_land: null,
        median_review_wait_hours: null,
        ...extra,
    }
}

function ticket(key: string, extra: Partial<ReportTicket> = {}): ReportTicket {
    return {
        key,
        title: null,
        landed_at: '2026-10-04T11:00:00Z',
        started_at: '2026-09-28T10:00:00Z',
        iterations: 1,
        pr_comments: 0,
        reviews: 1,
        changes_requested: 0,
        cost_usd: null,
        hours_to_land: 125,
        review_wait_hours: 3,
        merged_at: null,
        awaiting_review_at: null,
        ...extra,
    }
}

describe('reportSpan', () => {
    it('keeps a span the page offers but the default, as a number or its digits', () => {
        expect(reportSpan(6)).toBe(6)
        expect(reportSpan('24')).toBe(24)
        expect(reportSpan(12)).toBeUndefined()
        expect(reportSpan(7)).toBeUndefined()
        expect(reportSpan('six')).toBeUndefined()
    })
})

describe('reportMonth', () => {
    it('keeps a month written YYYY-MM, and nothing else', () => {
        expect(reportMonth('2026-10')).toBe('2026-10')
        expect(reportMonth('2026-13')).toBeUndefined()
        expect(reportMonth('2026-1')).toBeUndefined()
        expect(reportMonth(202_610)).toBeUndefined()
    })
})

describe('pickedMonth', () => {
    const months = [month('2026-09', 1), month('2026-10', 2)]

    it('shows the month chosen, else the latest', () => {
        expect(pickedMonth(months, '2026-09')?.month).toBe('2026-09')
        expect(pickedMonth(months, undefined)?.month).toBe('2026-10')
        expect(pickedMonth(months, '2025-01')?.month).toBe('2026-10')
        expect(pickedMonth([], undefined)).toBeUndefined()
    })
})

describe('monthLabel', () => {
    it('names a month short or long', () => {
        expect(monthLabel('2026-10')).toBe('Oct 2026')
        expect(monthLabel('2026-01', 'long')).toBe('January 2026')
    })
})

describe('reportLine', () => {
    it('says what the latest month cost and landed', () => {
        const landed = [{ key: 'ABC-1' }, { key: 'ABC-2' }] as ReportMonth['landed']
        expect(reportLine([month('2026-09', 1), month('2026-10', 12.5, { landed, pull_requests: 1 })])).toBe(
            '$12.50 in October 2026 · 2 tickets landed · 1 PR',
        )
        expect(reportLine([month('2026-10', null)])).toBe('– in October 2026 · no tickets landed · no PRs')
        expect(reportLine([])).toBe('')
    })
})

describe('tokens', () => {
    it('counts what was sent, the cache both ways included, and what was written, reasoning included', () => {
        expect(sentTokens(TOKENS)).toBe(10_000)
        expect(wroteTokens(TOKENS)).toBe(250)
    })
})

describe('hoursText', () => {
    it('says minutes under an hour, hours under two days, and days past them', () => {
        expect(hoursText(null)).toBe('–')
        expect(hoursText(0.5)).toBe('30m')
        expect(hoursText(5.25)).toBe('5.3h')
        expect(hoursText(72)).toBe('3.0d')
    })
})

describe('medianText', () => {
    it('writes a whole median whole, and a half with its tenth', () => {
        expect(medianText(null)).toBe('–')
        expect(medianText(3)).toBe('3')
        expect(medianText(2.5)).toBe('2.5')
    })
})

describe('outsideHint', () => {
    it('says what the row counts, as of the last read of the sessions, or that none is read yet', () => {
        const at = '2026-10-08T11:55:00Z'
        expect(outsideHint(at, DEFAULT_CLOCK)).toBe(
            "The runtime's sessions none of canopy's runs started, yours among them, counted in sessions, not runs, " +
                `as of ${stamp(at, DEFAULT_CLOCK)}.`,
        )
        expect(outsideHint(null, DEFAULT_CLOCK)).toMatch(/canopy loop has not read them yet, so none is counted\.$/u)
    })
})

describe('which clock a figure ran on', () => {
    const github = ticket('ABC-1', { merged_at: '2026-10-03T15:00:00Z', awaiting_review_at: '2026-09-29T16:00:00Z' })
    const proxied = ticket('ABC-2')
    const unknown = ticket('ABC-3', { hours_to_land: null, review_wait_hours: null })

    it("names GitHub's time where canopy kept one, else the proxy that stood in", () => {
        expect(toLandHint(github)).toBe("To its PR's merge, as GitHub timed it")
        expect(toLandHint(proxied)).toMatch(/^To the tick that marked it done/u)
        expect(reviewWaitHint(github)).toMatch(/^From when its PR began waiting on a review, as GitHub timed it/u)
        expect(reviewWaitHint(proxied)).toMatch(/^From the end of its first worker run that ended done/u)
        expect([toLandHint(unknown), reviewWaitHint(unknown)]).toEqual([undefined, undefined])
    })

    it("counts a month's figures that ran on GitHub's clock, leaving out the tickets with none", () => {
        expect(clockShare(month('2026-10', 1, { landed: [github, proxied, unknown] }), 'to land')).toBe(
            "1 of 2 from GitHub's times, the rest from proxies",
        )
        expect(clockShare(month('2026-10', 1, { landed: [github, github] }), 'review wait')).toBe(
            "All 2 from GitHub's times",
        )
        expect(clockShare(month('2026-10', 1, { landed: [proxied] }), 'review wait')).toBe(
            'From a proxy: canopy kept no time from GitHub',
        )
        expect(clockShare(month('2026-10', 1, { landed: [unknown] }), 'to land')).toBeUndefined()
    })
})
